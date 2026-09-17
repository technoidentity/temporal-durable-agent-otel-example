"""Agent graph nodes and the LLM builder.

The LLM is built entirely from config (never hardcoded). Two providers are
supported:

* ``openai`` — a real ``ChatOpenAI`` model.
* ``fake``   — a deterministic, offline tool-calling model so the full
  workflow -> agent -> tool -> agent path can be exercised without an API key.
"""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, convert_to_messages
from langchain_core.outputs import ChatGeneration, ChatResult

from app.agent.tools import ALL_TOOLS
from app.config.models import LLMConfig, LLMProvider
from app.observability.metrics import get_agent_metrics
from app.observability.tracing import get_tracer

# Nodes run inside Temporal Activities, where the graph state has crossed the
# payload boundary and its messages arrive as plain dicts (the plugin types node
# args as ``Any``, so no converter can restore the concrete message classes).
# ``convert_to_messages`` rebuilds proper AIMessage/ToolMessage/HumanMessage so
# tool-call detection and model input work correctly on every turn.
_TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}


class FakeToolCallingModel(BaseChatModel):
    """Offline chat model that deterministically drives one tool call.

    On the first turn (only human input) it emits a tool call to the first bound
    tool; once a ``ToolMessage`` is present it produces a final natural-language
    answer that embeds the tool result. This mirrors a real tool-calling LLM
    closely enough to demonstrate the end-to-end flow.
    """

    tool_names: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "FakeToolCallingModel":
        names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]
        return self.model_copy(update={"tool_names": names})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        tool_results = [m for m in messages if isinstance(m, ToolMessage)]
        if tool_results:
            message = AIMessage(content=f"The current UTC time is {tool_results[-1].content}.")
        elif self.tool_names:
            message = AIMessage(
                content="",
                tool_calls=[
                    {"name": self.tool_names[0], "args": {}, "id": "call_current_time"}
                ],
            )
        else:
            # No tools bound (e.g. multi-agent pipeline nodes): echo the input so
            # offline runs and tests produce deterministic, distinguishable output.
            last_human = next(
                (m.content for m in reversed(messages) if isinstance(m, HumanMessage)), ""
            )
            message = AIMessage(content=f"(fake) {str(last_human)[:160]}")
        return ChatResult(generations=[ChatGeneration(message=message)])


def build_llm(cfg: LLMConfig) -> BaseChatModel:
    """Construct the chat model from configuration."""
    if cfg.provider is LLMProvider.fake:
        return FakeToolCallingModel()

    if cfg.provider is LLMProvider.openai:
        if not cfg.api_key:
            raise ValueError(
                "llm.provider=openai requires an API key (set OPENAI_API_KEY)"
            )
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url or None,
            temperature=cfg.temperature,
        )

    if cfg.provider is LLMProvider.ollama:
        # Ollama exposes an OpenAI-compatible endpoint; reuse ChatOpenAI so
        # tool-calling works with capable local models. No API key required.
        from langchain_openai import ChatOpenAI

        base_url = (cfg.base_url or "http://localhost:11434").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        return ChatOpenAI(
            model=cfg.model,
            api_key=cfg.api_key or "ollama",
            base_url=base_url,
            temperature=cfg.temperature,
        )

    if cfg.provider is LLMProvider.lyzr:
        if not cfg.api_key or not cfg.lyzr_agent_id:
            raise ValueError(
                "llm.provider=lyzr requires api_key and lyzr_agent_id"
            )
        from app.agent.lyzr import LyzrChatModel

        kwargs: dict = {"api_key": cfg.api_key, "agent_id": cfg.lyzr_agent_id, "user_id": cfg.lyzr_user_id}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        return LyzrChatModel(**kwargs)

    raise ValueError(f"unsupported llm provider: {cfg.provider}")  # pragma: no cover


# The LangGraph Temporal plugin identifies nodes by their qualified name and
# therefore requires module-level functions (no closures/locals). We inject the
# configured model through module state set once at worker startup; activities
# run in the same worker process, so this is available when the node executes.
_llm_with_tools: Any | None = None
_model_name: str = "unknown"


def configure_agent(llm_with_tools: Any, model_name: str) -> None:
    """Bind the model used by :func:`agent_node`. Called at graph-build time."""
    global _llm_with_tools, _model_name
    _llm_with_tools = llm_with_tools
    _model_name = model_name


def agent_node(state: dict) -> dict:
    """LLM node. Runs as an Activity, so LLM calls/metrics/spans are safe here."""
    if _llm_with_tools is None:  # pragma: no cover - defensive
        raise RuntimeError("agent not configured; call configure_agent() at startup")
    messages = convert_to_messages(state["messages"])
    tracer = get_tracer()
    with tracer.start_as_current_span("agent.llm"):
        with get_agent_metrics().llm_call(_model_name):
            response = _llm_with_tools.invoke(messages)
    return {"messages": [response]}


def tools_node(state: dict) -> dict:
    """Execute the tools requested in the last AIMessage.

    Replaces LangGraph's ``ToolNode`` because that node's strict ``isinstance``
    check rejects the dict-shaped messages that reach an Activity. Each tool
    records its own metric/span (see ``app.agent.tools``).
    """
    messages = convert_to_messages(state["messages"])
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    outputs: list[ToolMessage] = []
    for call in tool_calls:
        name = call["name"]
        tool = _TOOLS_BY_NAME.get(name)
        if tool is None:
            # A hallucinated tool name must not raise (a retryable KeyError would
            # burn every attempt on deterministic output, review H5). Return an
            # error ToolMessage so the agent can self-correct on the next turn.
            outputs.append(
                ToolMessage(
                    content=f"Error: unknown tool '{name}'. Available: {sorted(_TOOLS_BY_NAME)}",
                    tool_call_id=call["id"],
                    name=name,
                    status="error",
                )
            )
            continue
        result = tool.invoke(call.get("args", {}))
        outputs.append(
            ToolMessage(content=str(result), tool_call_id=call["id"], name=name)
        )
    return {"messages": outputs}
