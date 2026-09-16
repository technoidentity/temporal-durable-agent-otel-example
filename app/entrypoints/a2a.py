"""Run an agent-to-agent call as a durable Temporal workflow.

    python -m app.entrypoints.a2a --agent servicenow --message "open incident: ..."
    python -m app.entrypoints.a2a --url http://localhost:8802 --message "hi"
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import click

from app.config import load_settings
from app.config.models import AppSettings
from app.observability import build_temporal_interceptors
from app.temporal.client import create_temporal_client
from app.workflows.a2a_workflow import A2AWorkflow, A2AWorkflowInput


async def execute(settings: AppSettings, target_url: str, message: str) -> str:
    interceptors = build_temporal_interceptors(settings)
    client = await create_temporal_client(settings, interceptors=interceptors)
    workflow_id = f"a2a-{uuid.uuid4().hex[:12]}"
    print(f"Workflow ID: {workflow_id}  ->  {target_url}")
    result = await client.execute_workflow(
        A2AWorkflow.run,
        A2AWorkflowInput(
            target_url=target_url,
            message=message,
            timeout_seconds=settings.a2a.call_timeout_seconds,
        ),
        id=workflow_id,
        task_queue=settings.temporal.task_queue,
        execution_timeout=timedelta(seconds=120),
    )
    print(f"Result: {result}")
    return result


@click.command()
@click.option("--agent", default=None, help="Agent name from config a2a.agents.")
@click.option("--url", default=None, help="Explicit A2A base URL (overrides --agent).")
@click.option("--message", "-m", required=True, help="Message to send.")
def main(agent, url, message) -> None:
    settings = load_settings()
    target_url = url
    if not target_url and agent:
        target_url = settings.a2a.agents.get(agent)
    if not target_url:
        raise SystemExit(
            "provide --url or --agent NAME present in config a2a.agents "
            f"(known: {list(settings.a2a.agents)})"
        )
    asyncio.run(execute(settings, target_url, message))


if __name__ == "__main__":
    main()
