"""Custom application metrics.

Instruments are created lazily from the global MeterProvider, so they are
no-ops until :func:`app.observability.telemetry.init_telemetry` installs a real
provider. All labels are low-cardinality (model, tool name, status) — never
workflow ids, prompts or user ids.
"""

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Iterator

from opentelemetry import metrics

_METER_NAME = "app.agent.metrics"


class AgentMetrics:
    """Thin wrapper around the OTel instruments used by the agent."""

    def __init__(self) -> None:
        meter = metrics.get_meter(_METER_NAME)
        self._llm_calls = meter.create_counter(
            "agent.llm.calls", unit="1", description="Number of LLM invocations"
        )
        self._llm_duration = meter.create_histogram(
            "agent.llm.duration", unit="s", description="LLM invocation latency"
        )
        self._tool_calls = meter.create_counter(
            "agent.tool.calls", unit="1", description="Number of tool invocations"
        )
        self._tool_duration = meter.create_histogram(
            "agent.tool.duration", unit="s", description="Tool invocation latency"
        )
        self._workflow_requests = meter.create_counter(
            "agent.workflow.requests", unit="1", description="Agent workflow requests"
        )
        self._workflow_failures = meter.create_counter(
            "agent.workflow.failures", unit="1", description="Agent workflow failures"
        )
        self._approvals = meter.create_counter(
            "agent.hitl.decisions", unit="1", description="HITL approval decisions"
        )
        self._chaos = meter.create_counter(
            "agent.chaos.injected", unit="1", description="Injected chaos faults"
        )

    # --- LLM ---------------------------------------------------------------- #
    @contextmanager
    def llm_call(self, model: str, agent: str = "") -> Iterator[dict]:
        """Time an LLM call and record calls/duration with a status label.

        ``agent`` is an optional low-cardinality role label (e.g. "inventory")
        so multi-agent pipelines can be broken down per agent.
        """
        labels = {"model": model, "status": "ok"}
        if agent:
            labels["agent"] = agent
        start = perf_counter()
        try:
            yield labels
        except Exception:
            labels["status"] = "error"
            raise
        finally:
            self._llm_calls.add(1, labels)
            self._llm_duration.record(perf_counter() - start, labels)

    # --- tools -------------------------------------------------------------- #
    @contextmanager
    def tool_call(self, tool_name: str) -> Iterator[dict]:
        labels = {"tool.name": tool_name, "status": "ok"}
        start = perf_counter()
        try:
            yield labels
        except Exception:
            labels["status"] = "error"
            raise
        finally:
            self._tool_calls.add(1, labels)
            self._tool_duration.record(perf_counter() - start, labels)

    # --- workflow ----------------------------------------------------------- #
    def workflow_requested(self) -> None:
        self._workflow_requests.add(1)

    def workflow_failed(self) -> None:
        self._workflow_failures.add(1)

    def approval_decided(self, approved: bool, via: str) -> None:
        # Low-cardinality labels: decision + how it was reached.
        self._approvals.add(
            1, {"decision": "approved" if approved else "rejected", "via": via}
        )

    def chaos_injected(self, mode: str, agent: str) -> None:
        self._chaos.add(1, {"mode": mode, "agent": agent})


_metrics: AgentMetrics | None = None


def get_agent_metrics() -> AgentMetrics:
    """Process-wide singleton, created on first use (after telemetry init)."""
    global _metrics
    if _metrics is None:
        _metrics = AgentMetrics()
    return _metrics
