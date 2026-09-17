"""Build Temporal retry policies and activity options from config."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio.common import RetryPolicy

from app.config.models import ActivityConfig


def build_retry_policy(activity: ActivityConfig) -> RetryPolicy:
    r = activity.retry
    return RetryPolicy(
        initial_interval=timedelta(seconds=r.initial_interval_seconds),
        backoff_coefficient=r.backoff_coefficient,
        maximum_interval=timedelta(seconds=r.maximum_interval_seconds),
        maximum_attempts=r.maximum_attempts,
        # Don't retry invalid-input / configuration errors — fail fast and clearly.
        non_retryable_error_types=list(r.non_retryable_error_types),
    )


def build_activity_options(activity: ActivityConfig) -> dict[str, Any]:
    """Activity options applied to LangGraph nodes that run as Activities.

    Passed through to ``workflow.execute_activity`` by the LangGraph plugin.
    Includes a heartbeat timeout so hung activities surface quickly and
    cancellation can be delivered.
    """
    return {
        "start_to_close_timeout": timedelta(seconds=activity.start_to_close_timeout_seconds),
        "heartbeat_timeout": timedelta(seconds=activity.heartbeat_timeout_seconds),
        "retry_policy": build_retry_policy(activity),
    }
