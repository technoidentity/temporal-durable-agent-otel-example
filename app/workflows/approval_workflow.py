"""Reusable, dedicated human-in-the-loop approval workflow.

Encapsulates the durable "wait for a human decision" pattern so any workflow can
delegate approvals to it as a child workflow. Also usable standalone.

Signal ``decide`` records the outcome; query ``pending`` lets a UI inspect the
open request; a durable timer applies the timeout policy if no one responds.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow


@dataclass
class ApprovalWorkflowInput:
    reason: str
    discount: float
    threshold: float
    details: str = ""
    timeout_seconds: int = 86400
    on_timeout: str = "reject"  # "reject" | "approve"


@workflow.defn
class ApprovalWorkflow:
    def __init__(self) -> None:
        self._decided: bool | None = None
        self._approver: str = ""
        self._note: str = ""
        self._via: str = ""
        self._req: ApprovalWorkflowInput | None = None

    @workflow.signal
    def decide(self, approved: bool, approver: str = "", note: str = "") -> None:
        if self._decided is None:
            self._decided = approved
            self._approver = approver
            self._note = note
            self._via = "human"

    @workflow.query
    def pending(self) -> dict:
        if self._decided is not None or self._req is None:
            return {"pending": False}
        r = self._req
        return {
            "pending": True,
            "reason": r.reason,
            "discount": r.discount,
            "threshold": r.threshold,
            "details": r.details,
        }

    @workflow.run
    async def run(self, inp: ApprovalWorkflowInput) -> dict:
        self._req = inp
        try:
            await workflow.wait_condition(
                lambda: self._decided is not None,
                timeout=timedelta(seconds=inp.timeout_seconds),
            )
        except asyncio.TimeoutError:
            pass

        if self._decided is None:
            self._decided = inp.on_timeout == "approve"
            self._via = "timeout"
            self._note = f"auto-{inp.on_timeout} on timeout"

        return {
            "approved": self._decided,
            "approver": self._approver,
            "note": self._note,
            "via": self._via,
        }
