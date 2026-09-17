"""Workflow execution entry point (the client side).

    python -m app.entrypoints.workflow --message "What time is it?"
    python -m app.entrypoints.workflow --message "..." --workflow-id my-id

Loads the same config, connects to Temporal, starts ``AgentWorkflow``, prints
the workflow id, waits for the result and prints the final agent response.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import click
from temporalio.common import WorkflowIDReusePolicy

from app.config import load_settings
from app.config.models import AppSettings
from app.observability import (
    build_temporal_interceptors,
    get_agent_metrics,
    init_telemetry,
)
from app.temporal.client import create_temporal_client
from app.temporal.runtime import create_runtime
from app.workflows.agent_workflow import AgentWorkflow, AgentWorkflowInput


async def execute(settings: AppSettings, message: str, workflow_id: str | None) -> str:
    workflow_id = workflow_id or f"{settings.langgraph.graph_name}-{uuid.uuid4().hex[:12]}"
    # Initialize telemetry on the client too, so the client span is real and the
    # distributed trace spans client -> workflow -> activities. shutdown() flushes.
    telemetry = init_telemetry(settings)
    metrics = get_agent_metrics()
    interceptors = build_temporal_interceptors(settings)
    client = await create_temporal_client(
        settings, runtime=create_runtime(settings), interceptors=interceptors
    )

    print(f"Workflow ID: {workflow_id}")
    metrics.workflow_requested()
    try:
        result = await client.execute_workflow(
            AgentWorkflow.run,
            AgentWorkflowInput(question=message, graph_name=settings.langgraph.graph_name),
            id=workflow_id,
            task_queue=settings.temporal.task_queue,
            execution_timeout=timedelta(
                seconds=settings.temporal.workflow.execution_timeout_seconds
            ),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except Exception:
        metrics.workflow_failed()
        raise
    finally:
        telemetry.shutdown()
    print(f"Result: {result}")
    return result


@click.command()
@click.option("--message", "-m", required=True, help="User message for the agent.")
@click.option("--workflow-id", "workflow_id", default=None, help="Optional workflow id.")
def main(message: str, workflow_id: str | None) -> None:
    settings = load_settings()
    asyncio.run(execute(settings, message, workflow_id))


if __name__ == "__main__":
    main()
