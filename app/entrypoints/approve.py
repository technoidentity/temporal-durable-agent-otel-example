"""Approve, reject, or inspect a pending human-in-the-loop approval.

    python -m app.entrypoints.approve --workflow-id ID --approve --note "ok"
    python -m app.entrypoints.approve --workflow-id ID --reject
    python -m app.entrypoints.approve --workflow-id ID --status
"""

from __future__ import annotations

import asyncio

import click

from app.config import load_settings
from app.config.models import AppSettings
from app.temporal.client import create_temporal_client
from app.workflows.order_workflow import OrderWorkflow


async def _run(settings: AppSettings, workflow_id: str, approved: bool | None, approver: str, note: str) -> None:
    client = await create_temporal_client(settings)
    handle = client.get_workflow_handle(workflow_id)
    if approved is None:
        pend = await handle.query(OrderWorkflow.pending)
        print(pend)
        return
    await handle.signal(OrderWorkflow.decide, args=[approved, approver, note])
    print(f"{'approved' if approved else 'rejected'} {workflow_id}")


@click.command()
@click.option("--workflow-id", "workflow_id", required=True)
@click.option("--approve", "approve_flag", is_flag=True, help="Approve the request.")
@click.option("--reject", "reject_flag", is_flag=True, help="Reject the request.")
@click.option("--status", "status_flag", is_flag=True, help="Show the pending request.")
@click.option("--approver", default="operator", help="Who is deciding.")
@click.option("--note", default="", help="Optional note.")
def main(workflow_id, approve_flag, reject_flag, status_flag, approver, note) -> None:
    settings = load_settings()
    if status_flag or (not approve_flag and not reject_flag):
        approved: bool | None = None
    elif approve_flag and reject_flag:
        raise SystemExit("choose one of --approve or --reject")
    else:
        approved = approve_flag
    asyncio.run(_run(settings, workflow_id, approved, approver, note))


if __name__ == "__main__":
    main()
