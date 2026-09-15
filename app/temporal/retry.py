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
    )


def build_activity_options(activity: ActivityConfig) -> dict[str, Any]:
    """Activity options applied to LangGraph nodes that run as Activities.

    Passed through to ``workflow.execute_activity`` by the LangGraph plugin.
    """
    return {
        "start_to_close_timeout": timedelta(seconds=activity.start_to_close_timeout_seconds),
        "retry_policy": build_retry_policy(activity),
    }
