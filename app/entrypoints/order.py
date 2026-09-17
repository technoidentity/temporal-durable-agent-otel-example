"""Start the multi-agent order workflow (with the HITL approval gate).

    python -m app.entrypoints.order --request "500 cases of Pepsi 330ml, 20% off"
    python -m app.entrypoints.order -r "..." --threshold 10 --timeout 120 --mode inline

If the requested discount exceeds the threshold the workflow pauses for a human
decision; approve/reject with `python -m app.entrypoints.approve`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import click
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy

from app.config import load_settings
from app.config.models import AppSettings
from app.observability import build_temporal_interceptors, get_agent_metrics, init_telemetry
from app.temporal.client import create_temporal_client
from app.temporal.runtime import create_runtime
from app.workflows.order_workflow import OrderWorkflow, OrderWorkflowInput


async def execute(settings: AppSettings, request: str, workflow_id: str | None, overrides: dict) -> dict:
    graph_name = settings.multi_agent.graph_name
    workflow_id = workflow_id or f"{graph_name}-{uuid.uuid4().hex[:12]}"
    hitl = settings.hitl

    sn = settings.third_party.servicenow
    inp = OrderWorkflowInput(
        request=request,
        graph_name=graph_name,
        hitl_enabled=overrides.get("hitl_enabled", hitl.enabled),
        hitl_mode=overrides.get("mode", hitl.mode.value),
        discount_threshold=overrides.get("threshold", hitl.discount_threshold),
        approval_timeout_seconds=overrides.get("timeout", hitl.approval_timeout_seconds),
        on_timeout=overrides.get("on_timeout", hitl.on_timeout.value),
        servicenow_a2a_url=sn.a2a_url if sn.enabled else "",
        open_incident_on_risk=sn.enabled and sn.open_incident_on_risk,
        risk_keywords=list(sn.risk_keywords),
        chaos=overrides.get("chaos", settings.chaos.as_spec()),
    )

    telemetry = init_telemetry(settings)
    metrics = get_agent_metrics()
    interceptors = build_temporal_interceptors(settings)
    # Runtime on the client too, so client-side SDK metrics are emitted (review L4).
    client = await create_temporal_client(
        settings, runtime=create_runtime(settings), interceptors=interceptors
    )

    metrics.workflow_requested()
    handle = await client.start_workflow(
        OrderWorkflow.run,
        inp,
        id=workflow_id,
        task_queue=settings.temporal.task_queue,
        execution_timeout=timedelta(
            seconds=settings.temporal.workflow.execution_timeout_seconds
        ),
        # Supplying a business key as --workflow-id then dedupes double-submits
        # (review M3); random ids get a fresh run each time.
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    print(f"Workflow ID: {workflow_id}")

    # Surface a pending approval (if the gate trips) so the operator knows how to act.
    for _ in range(30):
        try:
            pend = await handle.query(OrderWorkflow.pending)
        except Exception:
            pend = {"pending": False}
        if pend.get("pending"):
            print(f"\n[APPROVAL REQUIRED] {pend.get('details')}")
            print("Approve:  python -m app.entrypoints.approve --workflow-id "
                  f"{workflow_id} --approve")
            print("Reject :  python -m app.entrypoints.approve --workflow-id "
                  f"{workflow_id} --reject\n")
            break
        desc = await handle.describe()
        if desc.status != WorkflowExecutionStatus.RUNNING:
            break
        await asyncio.sleep(0.5)

    try:
        result = await handle.result()
    except Exception:
        metrics.workflow_failed()
        telemetry.shutdown()
        raise

    ap = result.get("approval", {})
    metrics.approval_decided(bool(ap.get("approved")), str(ap.get("via", "auto")))
    telemetry.shutdown()

    for stage in ["intake", "inventory", "pricing", "fulfillment", "account", "outcome"]:
        if result.get(stage):
            print(f"\n=== {stage} ===\n{result[stage]}")
    print(f"\n=== approval ===\n{ap}")
    if result.get("incident"):
        print(f"\n=== incident ===\n{result['incident']}")
    return result


@click.command()
@click.option("--request", "-r", "request", required=True, help="Distributor order request.")
@click.option("--workflow-id", "workflow_id", default=None, help="Optional workflow id.")
@click.option("--threshold", type=float, default=None, help="Discount %% approval threshold.")
@click.option("--timeout", type=int, default=None, help="Approval wait timeout (seconds).")
@click.option("--mode", type=click.Choice(["inline", "child"]), default=None, help="HITL mode.")
@click.option("--no-hitl", is_flag=True, help="Disable the approval gate for this run.")
@click.option("--chaos-target", default=None, help="Agent role to inject a fault into.")
@click.option("--chaos-mode", type=click.Choice(["transient_error", "permanent_error", "latency"]),
              default=None, help="Fault mode.")
@click.option("--chaos-attempts", type=int, default=1, help="Apply on attempts <= N (0=all).")
@click.option("--chaos-latency", type=float, default=0.0, help="Latency seconds (mode=latency).")
@click.option("--force-hitl", is_flag=True, help="Force the approval gate this run.")
def main(request, workflow_id, threshold, timeout, mode, no_hitl,
         chaos_target, chaos_mode, chaos_attempts, chaos_latency, force_hitl) -> None:
    settings = load_settings()
    if not settings.multi_agent.enabled:
        raise SystemExit("multi_agent.enabled is false; enable it in config to run orders")
    overrides: dict = {}
    if threshold is not None:
        overrides["threshold"] = threshold
    if timeout is not None:
        overrides["timeout"] = timeout
    if mode is not None:
        overrides["mode"] = mode
    if no_hitl:
        overrides["hitl_enabled"] = False
    if chaos_target or chaos_mode or force_hitl:
        overrides["chaos"] = {
            "target": chaos_target or "",
            "mode": chaos_mode or "none",
            "attempts": chaos_attempts,
            "latency_seconds": chaos_latency,
            "force_hitl": force_hitl,
        }
    asyncio.run(execute(settings, request, workflow_id, overrides))


if __name__ == "__main__":
    main()
