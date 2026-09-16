"""Dedicated agent-to-agent workflow.

Calls a remote A2A agent durably via an activity (the HTTP call is
nondeterministic, so it must be an activity). Reusable on its own and
composable into other workflows (e.g. the order flow reaching ServiceNow).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.temporal.a2a_activity import A2ACallInput, a2a_call_activity


@dataclass
class A2AWorkflowInput:
    target_url: str
    message: str
    context_id: str | None = None
    timeout_seconds: int = 30


@workflow.defn
class A2AWorkflow:
    @workflow.run
    async def run(self, inp: A2AWorkflowInput) -> str:
        return await workflow.execute_activity(
            a2a_call_activity,
            A2ACallInput(
                target_url=inp.target_url,
                message=inp.message,
                context_id=inp.context_id,
                timeout_seconds=float(inp.timeout_seconds),
            ),
            start_to_close_timeout=timedelta(seconds=inp.timeout_seconds + 15),
        )
