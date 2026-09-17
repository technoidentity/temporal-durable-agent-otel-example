"""The Temporal workflow that drives the LangGraph agent.

The workflow is deterministic: it never reads the clock, environment or config
at runtime. Everything it needs (the question and which registered graph to run)
arrives as a serializable input. The LangGraph plugin runs the nondeterministic
nodes (LLM, tools) as Activities.
"""

from __future__ import annotations

from dataclasses import dataclass

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from langchain_core.messages import convert_to_messages
    from temporalio.contrib.langgraph import graph


def _last_content(messages: list) -> str:
    """Read the final message's text, tolerating dicts crossing the payload
    boundary (review H3): a bare .content deref on a dict is an AttributeError
    inside workflow code, which retries forever and never surfaces."""
    if not messages:
        return ""
    normalized = convert_to_messages(messages)
    return str(getattr(normalized[-1], "content", "") or "")


@dataclass
class AgentWorkflowInput:
    """Deterministic input passed into the workflow at start time."""

    question: str
    graph_name: str


@workflow.defn
class AgentWorkflow:
    @workflow.run
    async def run(self, request: AgentWorkflowInput) -> str:
        app = graph(request.graph_name).compile()
        result = await app.ainvoke(
            {"messages": [{"role": "user", "content": request.question}]}
        )
        return _last_content(result.get("messages", []))
