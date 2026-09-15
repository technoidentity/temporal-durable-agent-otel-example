"""Temporal SDK runtime construction.

The runtime carries telemetry configuration for the Temporal *core* SDK. We use
the SDK's native OpenTelemetry metrics exporter (``OpenTelemetryConfig``) to
push worker/activity/workflow SDK metrics straight to the OTLP collector.

Note on the SDK API: earlier examples suggested a
``MetricBuffer -> MetricsExporter -> MeterProvider`` chain. In the current SDK
(temporalio 1.33) the supported way to ship SDK metrics over OTLP is
``TelemetryConfig(metrics=OpenTelemetryConfig(url=...))``; ``MetricBuffer`` is
for in-process consumption only. We use the native exporter — see the README.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio.runtime import (
    LoggingConfig,
    LoggingFormat,
    OpenTelemetryConfig,
    Runtime,
    TelemetryConfig,
    TelemetryFilter,
)

from app.config.models import AppSettings


def create_runtime(settings: AppSettings) -> Runtime | None:
    """Create a Temporal ``Runtime`` carrying SDK telemetry, or ``None``.

    Returns ``None`` when worker SDK metrics are disabled, in which case callers
    let the SDK use its default runtime. This keeps OTel strictly optional.
    """
    obs = settings.observability
    if not obs.worker_metrics_active:
        return None

    metrics = OpenTelemetryConfig(
        url=obs.otel.endpoint,
        metric_periodicity=timedelta(seconds=10),
        durations_as_seconds=True,
    )

    telemetry = TelemetryConfig(
        metrics=metrics,
        logging=LoggingConfig(
            filter=TelemetryFilter(core_level="WARN", other_level="ERROR"),
            format=LoggingFormat.JSON,
        ),
        metric_prefix="temporal_",
        # Let the collector supply service_name as a label from the OTLP resource
        # (resource_to_telemetry_conversion). If the SDK ALSO attaches it as a
        # data-point attribute, the Prometheus exporter sees the same label twice
        # ("duplicate label names in constant and variable labels") and drops the
        # whole metric. So we disable the SDK-side attribute and avoid global_tags
        # that would collide the same way.
        attach_service_name=False,
    )
    return Runtime(telemetry=telemetry)
