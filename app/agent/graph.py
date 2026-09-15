"""LangGraph construction for the hello-agent.

Graph shape::

    START -> agent --(tool call)--> tools -> agent
                 \\--(no tool)--> END

Both ``agent`` (LLM call) and ``tools`` (current_time) run as Temporal
Activities. Routing via ``tools_condition`` is a conditional edge and stays in
the deterministic workflow context.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition

from app.agent.nodes import agent_node, build_llm, configure_agent, tools_node
from app.agent.state import AgentState
from app.agent.tools import ALL_TOOLS
from app.config.models import AppSettings
from app.temporal.retry import build_activity_options


async def route_from_agent(state: dict) -> str:
    """Conditional edge: send to ``tools`` on a tool call, else ``END``.

    This routing runs in the deterministic workflow context. It is declared
    ``async`` on purpose: LangGraph awaits async edge functions directly, whereas
    a sync function is offloaded via ``run_in_executor`` — which Temporal's
    workflow event loop does not implement.
    """
    return tools_condition(state)


def build_graph(settings: AppSettings) -> StateGraph:
    """Build (but do not compile) the agent ``StateGraph``.

    The plugin compiles it inside the workflow. Node ``metadata`` carries
    ``execute_in`` plus the activity options (timeout + retry) derived from
    config.
    """
    llm = build_llm(settings.llm)
    llm_with_tools = llm.bind_tools(ALL_TOOLS)
    configure_agent(llm_with_tools, settings.llm.model)

    activity_metadata = {
        "execute_in": "activity",
        **build_activity_options(settings.temporal.activity),
    }

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node, metadata=activity_metadata)
    graph.add_node("tools", tools_node, metadata=activity_metadata)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_from_agent, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph
