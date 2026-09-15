"""OpenTelemetry setup for the application (traces + metrics).

This wires the OTel SDK to an OTLP endpoint (normally the collector). It is
entirely optional: when observability is disabled the OTel API falls back to
no-op providers, so ``get_tracer`` / ``get_meter`` elsewhere keep working
without any conditional code at the call sites.

Temporal *worker SDK* metrics are handled separately in
``app.temporal.runtime`` (they come from the Rust core via the SDK runtime, not
from this Python MeterProvider). Both converge on the same collector.
"""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry import metrics as otel_metrics
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config.models import AppSettings, OtelProtocol


def build_resource(settings: AppSettings) -> Resource:
    """Resource attributes shared by every span and metric."""
    return Resource.create(
        {
            "service.name": settings.observability.service_name,
            "service.namespace": settings.app.name,
            "service.version": "0.1.0",
            "deployment.environment": settings.app.environment.value,
            "temporal.namespace": settings.temporal.namespace,
            "temporal.task_queue": settings.temporal.task_queue,
        }
    )


def _span_exporter(settings: AppSettings):
    endpoint = settings.observability.otel.endpoint
    if settings.observability.otel.protocol is OtelProtocol.http:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))


def _metric_exporter(settings: AppSettings):
    endpoint = settings.observability.otel.endpoint
    if settings.observability.otel.protocol is OtelProtocol.http:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        return OTLPMetricExporter(endpoint=endpoint.rstrip("/") + "/v1/metrics")
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

    return OTLPMetricExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))


@dataclass
class TelemetryHandle:
    """Owns the providers so the caller can flush/shutdown on exit."""

    tracer_provider: TracerProvider | None
    meter_provider: MeterProvider | None

    def shutdown(self) -> None:
        if self.tracer_provider is not None:
            self.tracer_provider.shutdown()
        if self.meter_provider is not None:
            self.meter_provider.shutdown()


def init_telemetry(settings: AppSettings) -> TelemetryHandle:
    """Install global OTel providers according to config. Idempotent per process.

    Returns a handle whose ``shutdown()`` flushes exporters. If neither traces
    nor metrics are active this is a no-op and returns an empty handle.
    """
    obs = settings.observability
    resource = build_resource(settings)

    tracer_provider: TracerProvider | None = None
    if obs.traces_active:
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(_span_exporter(settings)))
        otel_trace.set_tracer_provider(tracer_provider)

    meter_provider: MeterProvider | None = None
    if obs.metrics_active:
        reader = PeriodicExportingMetricReader(
            _metric_exporter(settings), export_interval_millis=15000
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        otel_metrics.set_meter_provider(meter_provider)

    return TelemetryHandle(tracer_provider=tracer_provider, meter_provider=meter_provider)
