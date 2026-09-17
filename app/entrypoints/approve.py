"""Approve, reject, or inspect a pending human-in-the-loop approval.

    python -m app.entrypoints.approve --workflow-id ID --approve --note "ok"
    python -m app.entrypoints.approve --workflow-id ID --reject
    python -m app.entrypoints.approve --workflow-id ID --status
"""

from __future__ import annotations

import asyncio

import click
from temporalio.client import WorkflowExecutionStatus, WorkflowUpdateFailedError

from app.config import load_settings
from app.config.models import AppSettings
from app.temporal.client import create_temporal_client
from app.workflows.approval_workflow import ApprovalWorkflow
from app.workflows.order_workflow import OrderWorkflow


async def _resolve_gate(client, parent_id: str):
    """Return (handle, workflow_class) for wherever the gate actually lives.

    In child mode the gate is on a child workflow at ``<parent>-approval`` and
    signalling the parent does nothing (review B2). Auto-detect the child so the
    same command works for inline and child modes.
    """
    child_id = f"{parent_id}-approval"
    try:
        child = client.get_workflow_handle(child_id)
        desc = await child.describe()
        if desc.status == WorkflowExecutionStatus.RUNNING:
            return child, ApprovalWorkflow
    except Exception:
        pass  # no child -> inline gate on the parent
    return client.get_workflow_handle(parent_id), OrderWorkflow


async def _run(settings: AppSettings, workflow_id: str, approved: bool | None, approver: str, note: str) -> None:
    client = await create_temporal_client(settings)
    handle, wf = await _resolve_gate(client, workflow_id)
    if approved is None:
        print(await handle.query(wf.pending))
        return
    # Update (not signal): the decision is confirmed atomically and a decision on
    # a closed/already-decided gate is rejected by the validator (review L1).
    try:
        await handle.execute_update(wf.decide_update, args=[approved, approver, note])
    except WorkflowUpdateFailedError as exc:
        raise SystemExit(f"decision rejected: {exc.cause}")
    print(f"{'approved' if approved else 'rejected'} {handle.id}")


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
