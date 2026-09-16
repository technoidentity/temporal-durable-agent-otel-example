"""LangGraph tools.

Each tool runs inside a Temporal Activity (the node that hosts it is tagged
``execute_in="activity"``), so nondeterministic work such as reading the clock
is safe here and never runs in workflow/replay context.
"""

from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.tools import tool

from app.observability.metrics import get_agent_metrics
from app.observability.tracing import get_tracer


@tool
def current_time() -> str:
    """Return the current time in UTC as an ISO-8601 string."""
    tracer = get_tracer()
    with tracer.start_as_current_span("tool.current_time"):
        with get_agent_metrics().tool_call("current_time"):
            return datetime.now(timezone.utc).isoformat()


ALL_TOOLS = [current_time]

__all__ = ["current_time", "ALL_TOOLS"]
