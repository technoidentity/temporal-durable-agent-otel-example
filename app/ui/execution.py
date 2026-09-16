"""Read-only projection of Temporal history for the workflow explorer.

No progress is invented: committed activity events provide outputs and timings,
and DescribeWorkflowExecution supplies in-flight attempts (including retries that
Temporal deliberately does not append individually to history).
"""

from __future__ import annotations

from typing import Any

from temporalio.converter import DataConverter


def _time(stamp: Any) -> str | None:
    return stamp.ToJsonString() if stamp and stamp.seconds else None


def _failure(failure: Any) -> str:
    messages = []
    while failure and failure.message:
        if failure.message not in messages:
            messages.append(failure.message)
        failure = failure.cause if failure.HasField("cause") else None
    return ": ".join(messages)


async def execution_view(handle: Any, desc: Any, roles: list[str], converter=None) -> dict:
    converter = converter or DataConverter.default
    history = await handle.fetch_history()
    known = set(roles)
    # Stages are built progressively: a step appears only once it is actually
    # scheduled in history, so the UI graph is constructed as the run executes
    # (the real flow/agents hit) rather than shown up front. ``order`` preserves
    # the configured pipeline order for a stable left-to-right layout.
    stages: dict[str, dict] = {}
    scheduled: dict[int, dict] = {}
    timeline = []
    child_id = None
    error = None
    request = ""
    options = {}
    started_at = closed_at = None
    incident = None

    async def decode(payloads):
        if not payloads.payloads:
            return None
        try:
            values = await converter.decode(payloads.payloads)
            return values[0] if values else None
        except Exception:
            return None  # Encrypted/unsupported payloads are not fabricated.

    for event in history.events:
        kind = event.WhichOneof("attributes")
        if not kind:
            continue
        attr = getattr(event, kind)
        at = _time(event.event_time)
        if kind == "workflow_execution_started_event_attributes":
            started_at = at
            inp = await decode(attr.input)
            if isinstance(inp, dict):
                request = inp.get("request", "")
                options = {k: inp.get(k) for k in ("hitl_enabled", "hitl_mode", "discount_threshold", "chaos")}
            timeline.append({"id": event.event_id, "at": at, "label": "Workflow started", "kind": "workflow"})
        elif kind == "activity_task_scheduled_event_attributes":
            role = attr.activity_type.name.rsplit(".", 1)[-1]
            if attr.activity_type.name == "a2a_call_activity":
                role = "servicenow"
            if role not in known and role != "servicenow":
                continue
            stage = stages.get(role)
            if stage is None:
                stage = {"role": role, "status": "waiting", "attempt": 0,
                         "order": len(stages)}
                stages[role] = stage
                if role == "servicenow":
                    incident = stage
            stage.update(status="scheduled", activity_id=attr.activity_id, scheduled_at=at)
            inp = await decode(attr.input)
            if isinstance(inp, dict):
                args = inp.get("args", [])
                stage["input"] = args[0] if args else inp
            scheduled[event.event_id] = stage
        elif kind.startswith("activity_task_"):
            stage = scheduled.get(getattr(attr, "scheduled_event_id", -1))
            if stage is None:
                continue
            role = stage["role"]
            if kind == "activity_task_started_event_attributes":
                stage.update(status="running", started_at=at, attempt=attr.attempt)
                if attr.HasField("last_failure"):
                    stage["last_failure"] = _failure(attr.last_failure)
                timeline.append({"id": event.event_id, "at": at, "role": role,
                                 "label": f"{role.title()} started", "kind": "agent", "attempt": attr.attempt})
            elif kind == "activity_task_completed_event_attributes":
                decoded = await decode(attr.result)
                output = decoded.get("result", decoded) if isinstance(decoded, dict) else decoded
                if isinstance(output, dict):
                    output = output.get("outcome" if role == "supervisor" else role, output)
                stage.update(status="completed", completed_at=at, output=output)
                timeline.append({"id": event.event_id, "at": at, "role": role,
                                 "label": f"{role.title()} completed", "kind": "completed"})
            elif kind in ("activity_task_failed_event_attributes", "activity_task_timed_out_event_attributes",
                          "activity_task_canceled_event_attributes"):
                message = _failure(attr.failure) if hasattr(attr, "failure") else "Activity canceled"
                stage.update(status="failed", completed_at=at, error=message)
                timeline.append({"id": event.event_id, "at": at, "role": role,
                                 "label": f"{role.title()} failed", "kind": "failed"})
        elif kind == "child_workflow_execution_started_event_attributes":
            if attr.workflow_type.name == "ApprovalWorkflow":
                child_id = attr.workflow_execution.workflow_id
                timeline.append({"id": event.event_id, "at": at, "label": "Approval child workflow started", "kind": "approval"})
        elif kind == "workflow_execution_signaled_event_attributes" and attr.signal_name == "decide":
            timeline.append({"id": event.event_id, "at": at, "label": "Human decision received", "kind": "approval"})
        elif kind in ("workflow_execution_completed_event_attributes", "workflow_execution_failed_event_attributes",
                      "workflow_execution_timed_out_event_attributes", "workflow_execution_terminated_event_attributes",
                      "workflow_execution_canceled_event_attributes"):
            closed_at = at
            if hasattr(attr, "failure"):
                error = _failure(attr.failure)
            timeline.append({"id": event.event_id, "at": at,
                             "label": f"Workflow {desc.status.name.lower().replace('_', ' ')}", "kind": "workflow"})

    raw = getattr(desc, "raw_description", None)
    if raw is not None:
        by_id = {s.get("activity_id"): s for s in scheduled.values()}
        for pending in raw.pending_activities:
            stage = by_id.get(pending.activity_id)
            if stage is None or stage["status"] in ("completed", "failed"):
                continue
            stage["attempt"] = pending.attempt
            stage["status"] = "running" if pending.state == 2 else ("retrying" if pending.attempt > 1 else "scheduled")
            if pending.HasField("last_started_time"):
                stage["started_at"] = _time(pending.last_started_time)
            if pending.HasField("last_failure"):
                stage["last_failure"] = _failure(pending.last_failure)
        if closed_at is None:
            closed_at = getattr(desc, "close_time", None)
            closed_at = closed_at.isoformat() if closed_at else None

    return {"stages": list(stages.values()), "timeline": timeline, "child_workflow_id": child_id,
            "error": error, "request": request, "options": options, "started_at": started_at,
            "closed_at": closed_at, "incident_activity": incident}
