"""Start the multi-agent order workflow.

    python -m app.entrypoints.order --request "500 cases of Pepsi 330ml, 20% off"
    python -m app.entrypoints.order --request "..." --workflow-id my-id
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import click

from app.config import load_settings
from app.config.models import AppSettings
from app.observability import build_temporal_interceptors, get_agent_metrics, init_telemetry
from app.temporal.client import create_temporal_client
from app.workflows.order_workflow import OrderWorkflow, OrderWorkflowInput


async def execute(settings: AppSettings, request: str, workflow_id: str | None) -> dict:
    graph_name = settings.multi_agent.graph_name
    workflow_id = workflow_id or f"{graph_name}-{uuid.uuid4().hex[:12]}"
    telemetry = init_telemetry(settings)
    metrics = get_agent_metrics()
    interceptors = build_temporal_interceptors(settings)
    client = await create_temporal_client(settings, interceptors=interceptors)

    print(f"Workflow ID: {workflow_id}")
    metrics.workflow_requested()
    try:
        result = await client.execute_workflow(
            OrderWorkflow.run,
            OrderWorkflowInput(request=request, graph_name=graph_name),
            id=workflow_id,
            task_queue=settings.temporal.task_queue,
            execution_timeout=timedelta(
                seconds=settings.temporal.workflow.execution_timeout_seconds
            ),
        )
    except Exception:
        metrics.workflow_failed()
        raise
    finally:
        telemetry.shutdown()

    stage_order = ["intake", "inventory", "pricing", "fulfillment", "account", "outcome"]
    for stage in stage_order:
        if result.get(stage):
            print(f"\n=== {stage} ===\n{result[stage]}")
    return result


@click.command()
@click.option("--request", "-r", "request", required=True, help="Distributor order request.")
@click.option("--workflow-id", "workflow_id", default=None, help="Optional workflow id.")
def main(request: str, workflow_id: str | None) -> None:
    settings = load_settings()
    if not settings.multi_agent.enabled:
        raise SystemExit("multi_agent.enabled is false; enable it in config to run orders")
    asyncio.run(execute(settings, request, workflow_id))


if __name__ == "__main__":
    main()
