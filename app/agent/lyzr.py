"""LangChain chat model backed by the Lyzr Agent API (the model router).

Lyzr's inference endpoint runs a configured agent and returns its text
response; the underlying model is selected on the Lyzr side, so the Lyzr
``x-api-key`` covers LLM access. It does not return OpenAI-style ``tool_calls``,
so this model is used for reasoning/summarization agents; deterministic tools
run as Temporal activities orchestrated by LangGraph.

API: ``POST {base_url}/v3/inference/chat/`` with header ``x-api-key``.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

_DEFAULT_BASE_URL = "https://agent-prod.studio.lyzr.ai"


class LyzrChatModel(BaseChatModel):
    """Minimal Lyzr-backed chat model.

    The last human/most-recent message becomes the Lyzr ``message``; any system
    messages are joined into ``system_prompt_variables['system']`` so callers can
    steer per-agent behavior. A per-instance ``session_id`` keeps Lyzr's own
    memory coherent within a run.
    """

    api_key: str
    agent_id: str
    user_id: str = "devex-demo"
    base_url: str = _DEFAULT_BASE_URL
    timeout_seconds: float = 60.0
    session_id: str = ""

    @property
    def _llm_type(self) -> str:
        return "lyzr"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "LyzrChatModel":
        # Lyzr manages tools on its side; nothing to bind for our tool flow.
        return self

    def _payload(self, messages: list[BaseMessage]) -> dict:
        system = "\n".join(
            str(m.content) for m in messages if isinstance(m, SystemMessage)
        )
        latest = next(
            (m for m in reversed(messages) if not isinstance(m, SystemMessage)),
            None,
        )
        message = str(latest.content) if latest is not None else ""
        payload: dict[str, Any] = {
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id or f"{self.user_id}-{uuid.uuid4().hex[:8]}",
            "message": message,
        }
        if system:
            payload["system_prompt_variables"] = {"system": system}
        return payload

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        url = self.base_url.rstrip("/") + "/v3/inference/chat/"
        headers = {"Content-Type": "application/json", "x-api-key": self.api_key}
        resp = httpx.post(
            url, json=self._payload(messages), headers=headers, timeout=self.timeout_seconds
        )
        resp.raise_for_status()
        data = resp.json()
        # Lyzr returns the agent text under "response"; tolerate a couple shapes.
        content = (
            data.get("response")
            or data.get("message")
            or (data if isinstance(data, str) else "")
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=str(content)))])
