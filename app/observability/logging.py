"""Structured logging via structlog, correlated with the active OTel span.

Emits JSON logs enriched with service/environment/temporal context and, when a
span is active, ``trace_id`` / ``span_id`` so logs join up with traces. Secrets
and prompt bodies are never added here; call sites decide what to log.
"""

from __future__ import annotations

import logging

import structlog
from opentelemetry import trace

from app.config.models import AppSettings


def _add_otel_context(_logger, _method, event_dict):
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_logging(settings: AppSettings) -> structlog.stdlib.BoundLogger:
    """Configure structlog once and return a base logger with static context."""
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_otel_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger().bind(
        service=settings.observability.service_name,
        environment=settings.app.environment.value,
        temporal_namespace=settings.temporal.namespace,
        task_queue=settings.temporal.task_queue,
    )


def get_logger(**context) -> structlog.stdlib.BoundLogger:
    """Get a logger with optional extra bound context."""
    return structlog.get_logger().bind(**context)
