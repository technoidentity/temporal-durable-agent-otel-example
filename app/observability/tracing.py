"""Tracing helpers: a tracer accessor and the Temporal tracing interceptor."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.trace import Tracer

from app.config.models import AppSettings

_TRACER_NAME = "app.agent"


def get_tracer() -> Tracer:
    """Application tracer. Returns a no-op tracer if telemetry is not installed."""
    return trace.get_tracer(_TRACER_NAME)


def build_temporal_interceptors(settings: AppSettings) -> list:
    """Return Temporal client interceptors for distributed tracing.

    Uses Temporal's OpenTelemetry ``TracingInterceptor`` so that client calls,
    workflow tasks and activities are linked into a single trace and context is
    propagated across the workflow/activity boundary. Empty when tracing is off.
    """
    if not settings.observability.traces_active:
        return []
    from temporalio.contrib.opentelemetry import TracingInterceptor

    return [TracingInterceptor(tracer=get_tracer())]
