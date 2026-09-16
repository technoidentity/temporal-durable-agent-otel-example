"""PepsiCo multi-agent order pipeline (LangGraph graph, run durably on Temporal).

Each role is a module-level node (required by the LangGraph Temporal plugin) that
delegates reasoning to a per-role LLM. With ``provider: lyzr`` each role maps to a
distinct Lyzr agent id; other providers reuse the global model. Nodes run as
Temporal activities; the pipeline order is config-driven.

State is plain strings, so it crosses the activity boundary without message
reconstruction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.agent.nodes import build_llm
from app.config.models import AppSettings, LLMConfig, LLMProvider
from app.observability.metrics import get_agent_metrics
from app.observability.tracing import get_tracer
from app.temporal.retry import build_activity_options


class OrderState(TypedDict, total=False):
    request: str
    intake: str
    inventory: str
    pricing: str
    fulfillment: str
    account: str
    outcome: str


# Role -> LLM, populated at graph-build time (worker startup). Activities run in
# the same worker process, so this registry is available when nodes execute.
_AGENTS: dict[str, BaseChatModel] = {}
_MODEL_LABEL: str = "lyzr"

KNOWN_ROLES = ["intake", "inventory", "pricing", "fulfillment", "account", "supervisor"]


def _run(role: str, prompt: str) -> str:
    llm = _AGENTS[role]
    tracer = get_tracer()
    with tracer.start_as_current_span(f"agent.{role}"):
        with get_agent_metrics().llm_call(_MODEL_LABEL, agent=role):
            return str(llm.invoke(prompt).content)


# --- prompt shaping per role ------------------------------------------------- #
def _p_intake(s: OrderState) -> str:
    return f"Distributor order request:\n{s.get('request', '')}"


def _p_inventory(s: OrderState) -> str:
    return f"Order: {s.get('request', '')}\nIntake summary: {s.get('intake', '')}"


def _p_pricing(s: OrderState) -> str:
    return (
        f"Order: {s.get('request', '')}\nIntake: {s.get('intake', '')}\n"
        f"Inventory: {s.get('inventory', '')}"
    )


def _p_fulfillment(s: OrderState) -> str:
    return (
        f"Order: {s.get('request', '')}\nInventory: {s.get('inventory', '')}\n"
        f"Pricing: {s.get('pricing', '')}"
    )


def _p_account(s: OrderState) -> str:
    return f"Order: {s.get('request', '')}\nIntake: {s.get('intake', '')}"


def _p_supervisor(s: OrderState) -> str:
    return (
        "Summarize the final outcome for the distributor based on:\n"
        f"- Intake: {s.get('intake', '')}\n- Inventory: {s.get('inventory', '')}\n"
        f"- Pricing: {s.get('pricing', '')}\n- Fulfillment: {s.get('fulfillment', '')}\n"
        f"- Account: {s.get('account', '')}"
    )


# --- module-level nodes (one per role) --------------------------------------- #
def intake_node(state: OrderState) -> dict:
    return {"intake": _run("intake", _p_intake(state))}


def inventory_node(state: OrderState) -> dict:
    return {"inventory": _run("inventory", _p_inventory(state))}


def pricing_node(state: OrderState) -> dict:
    return {"pricing": _run("pricing", _p_pricing(state))}


def fulfillment_node(state: OrderState) -> dict:
    return {"fulfillment": _run("fulfillment", _p_fulfillment(state))}


def account_node(state: OrderState) -> dict:
    return {"account": _run("account", _p_account(state))}


def supervisor_node(state: OrderState) -> dict:
    return {"outcome": _run("supervisor", _p_supervisor(state))}


_NODES: dict[str, Callable[[OrderState], dict]] = {
    "intake": intake_node,
    "inventory": inventory_node,
    "pricing": pricing_node,
    "fulfillment": fulfillment_node,
    "account": account_node,
    "supervisor": supervisor_node,
}


def _load_lyzr_agents(settings: AppSettings) -> dict[str, Any]:
    path = Path(settings.multi_agent.lyzr_agents_file)
    if not path.is_file():
        raise FileNotFoundError(
            f"lyzr agents file not found: {path} (run scripts/lyzr_provision.py)"
        )
    return yaml.safe_load(path.read_text()) or {}


def _build_agents(settings: AppSettings, roles: list[str]) -> None:
    """Populate the role -> LLM registry according to the configured provider."""
    global _MODEL_LABEL
    _AGENTS.clear()
    provider = settings.llm.provider
    _MODEL_LABEL = provider.value

    if provider is LLMProvider.lyzr:
        doc = _load_lyzr_agents(settings)
        base_url = doc.get("base_url", "")
        agents_map = doc.get("agents", {})
        for role in roles:
            key = f"{settings.multi_agent.name_prefix}{role}"
            agent_id = agents_map.get(key)
            if not agent_id:
                raise ValueError(f"no Lyzr agent id for role '{role}' (key '{key}')")
            cfg = LLMConfig(
                provider=LLMProvider.lyzr,
                api_key=settings.llm.api_key,
                base_url=base_url or settings.llm.base_url,
                lyzr_agent_id=str(agent_id),
                lyzr_user_id=settings.llm.lyzr_user_id,
            )
            _AGENTS[role] = build_llm(cfg)
    else:
        # fake / ollama / openai: one model instance reused per role.
        for role in roles:
            _AGENTS[role] = build_llm(settings.llm)


def build_order_graph(settings: AppSettings) -> StateGraph:
    """Build the multi-agent order pipeline graph (not compiled)."""
    roles = [r for r in settings.multi_agent.pipeline if r in _NODES]
    if not roles:
        raise ValueError("multi_agent.pipeline has no known roles")

    _build_agents(settings, roles)

    activity_metadata = {
        "execute_in": "activity",
        **build_activity_options(settings.temporal.activity),
    }

    graph = StateGraph(OrderState)
    for role in roles:
        graph.add_node(role, _NODES[role], metadata=activity_metadata)

    graph.add_edge(START, roles[0])
    for a, b in zip(roles, roles[1:]):
        graph.add_edge(a, b)
    graph.add_edge(roles[-1], END)
    return graph
