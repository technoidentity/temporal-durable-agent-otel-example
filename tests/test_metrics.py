"""Metrics/telemetry initialization (in-memory, no exporter network calls)."""

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from app.config.models import AppSettings
from app.observability.metrics import AgentMetrics
from app.observability.telemetry import build_resource


def test_build_resource_has_required_attributes():
    attrs = build_resource(AppSettings()).attributes
    for key in (
        "service.name",
        "service.namespace",
        "deployment.environment",
        "temporal.namespace",
        "temporal.task_queue",
    ):
        assert key in attrs


def test_agent_metrics_record(monkeypatch):
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(metrics, "get_meter", lambda name: provider.get_meter(name))

    m = AgentMetrics()
    with m.llm_call(model="gpt-test"):
        pass
    with m.tool_call(tool_name="current_time"):
        pass
    m.workflow_requested()

    data = reader.get_metrics_data()
    names = {
        metric.name
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for metric in sm.metrics
    }
    assert "agent.llm.calls" in names
    assert "agent.tool.calls" in names
    assert "agent.workflow.requests" in names


def test_metrics_error_status(monkeypatch):
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(metrics, "get_meter", lambda name: provider.get_meter(name))

    m = AgentMetrics()
    try:
        with m.tool_call(tool_name="boom"):
            raise RuntimeError("fail")
    except RuntimeError:
        pass

    data = reader.get_metrics_data()
    points = [
        point
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for metric in sm.metrics
        if metric.name == "agent.tool.calls"
        for point in metric.data.data_points
    ]
    assert any(p.attributes.get("status") == "error" for p in points)
