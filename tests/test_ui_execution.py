"""History projection tests use real Temporal protobufs and payload conversion."""
from types import SimpleNamespace

import pytest
from temporalio.api.history.v1 import (
    HistoryEvent, ActivityTaskScheduledEventAttributes,
    ActivityTaskStartedEventAttributes, ActivityTaskCompletedEventAttributes,
    ActivityTaskFailedEventAttributes, WorkflowExecutionStartedEventAttributes,
)
from temporalio.api.common.v1 import ActivityType, Payloads
from temporalio.api.failure.v1 import Failure
from temporalio.api.workflow.v1 import PendingActivityInfo
from temporalio.converter import DataConverter

from app.ui.execution import execution_view


class HistoryHandle:
    def __init__(self, events):
        self.events = events

    async def fetch_history(self):
        return SimpleNamespace(events=self.events)


async def payload(value):
    return Payloads(payloads=await DataConverter.default.encode([value]))


@pytest.mark.asyncio
async def test_projects_real_activity_outputs_and_retry_attempt():
    events = [
        HistoryEvent(event_id=1, workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
            input=await payload({"request": "order", "hitl_mode": "inline"}))),
        HistoryEvent(event_id=5, activity_task_scheduled_event_attributes=ActivityTaskScheduledEventAttributes(
            activity_id="1", activity_type=ActivityType(name="pepsico-order.intake"),
            input=await payload({"args": [{"request": "order"}]}))),
        HistoryEvent(event_id=6, activity_task_started_event_attributes=ActivityTaskStartedEventAttributes(
            scheduled_event_id=5, attempt=2, last_failure=Failure(message="temporary failure"))),
        HistoryEvent(event_id=7, activity_task_completed_event_attributes=ActivityTaskCompletedEventAttributes(
            scheduled_event_id=5, result=await payload({"result": {"intake": "Actual intake output"}}))),
    ]
    view = await execution_view(HistoryHandle(events), SimpleNamespace(status=SimpleNamespace(name="RUNNING")), ["intake", "inventory"])
    assert view["request"] == "order"
    assert view["stages"][0]["output"] == "Actual intake output"
    assert view["stages"][0]["input"] == {"request": "order"}
    assert view["stages"][0]["attempt"] == 2
    assert view["stages"][0]["last_failure"] == "temporary failure"
    # Progressive graph: only steps actually reached are projected; inventory
    # has not been scheduled yet, so it is not rendered.
    assert [s["role"] for s in view["stages"]] == ["intake"]
    assert len(view["timeline"]) == 3


@pytest.mark.asyncio
async def test_pending_attempt_is_reported_without_inventing_history():
    event = HistoryEvent(event_id=5, activity_task_scheduled_event_attributes=ActivityTaskScheduledEventAttributes(
        activity_id="2", activity_type=ActivityType(name="pepsico-order.inventory")))
    pending = PendingActivityInfo(activity_id="2", state=1, attempt=2, last_failure=Failure(message="retry me"))
    desc = SimpleNamespace(raw_description=SimpleNamespace(pending_activities=[pending]))
    view = await execution_view(HistoryHandle([event]), desc, ["inventory"])
    stage = view["stages"][0]
    assert stage["status"] == "retrying"
    assert stage["attempt"] == 2
    assert stage["last_failure"] == "retry me"
    assert view["timeline"] == []


@pytest.mark.asyncio
async def test_failed_agent_preserves_cause_and_leaves_later_steps_unrendered():
    events = [HistoryEvent(event_id=5, activity_task_scheduled_event_attributes=ActivityTaskScheduledEventAttributes(
        activity_id="1", activity_type=ActivityType(name="pepsico-order.intake"))),
        HistoryEvent(event_id=8, activity_task_failed_event_attributes=ActivityTaskFailedEventAttributes(
            scheduled_event_id=5, failure=Failure(message="Activity failed", cause=Failure(message="Injected fault"))))]
    view = await execution_view(HistoryHandle(events), SimpleNamespace(), ["intake", "pricing"])
    assert view["stages"][0]["status"] == "failed"
    assert view["stages"][0]["error"] == "Activity failed: Injected fault"
    # Progressive graph: pricing has not been reached, so it is not rendered yet.
    assert [s["role"] for s in view["stages"]] == ["intake"]
