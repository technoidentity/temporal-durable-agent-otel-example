"""Durable Temporal workflow for the PepsiCo multi-agent order pipeline.

Deterministic: it invokes the registered graph with a serializable input, then
applies a human-in-the-loop approval gate when the requested discount exceeds a
configurable threshold. The gate can run inline (signal/query/timer on this
workflow) or be delegated to the reusable ApprovalWorkflow (child workflow).
All gate parameters arrive in the input so the workflow reads no config/env.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from temporalio.contrib.langgraph import graph

    from app.platform.hitl import needs_approval, parse_discount
    from app.workflows.approval_workflow import ApprovalWorkflow, ApprovalWorkflowInput

_STAGES = ("intake", "inventory", "pricing", "fulfillment", "account", "outcome")


@dataclass
class OrderWorkflowInput:
    request: str
    graph_name: str
    hitl_enabled: bool = True
    hitl_mode: str = "inline"  # "inline" | "child"
    discount_threshold: float = 15.0
    approval_timeout_seconds: int = 86400
    on_timeout: str = "reject"  # "reject" | "approve"
    # Third-party (ServiceNow) leg: open an incident over A2A on fulfillment risk.
    servicenow_a2a_url: str = ""
    open_incident_on_risk: bool = False
    risk_keywords: list[str] = field(default_factory=list)
    # Chaos / fault-injection spec (see app.platform.chaos).
    chaos: dict = field(default_factory=dict)


@workflow.defn
class OrderWorkflow:
    def __init__(self) -> None:
        self._decided: bool | None = None
        self._approver: str = ""
        self._note: str = ""
        self._via: str = ""
        self._pending: dict | None = None

    @workflow.signal
    def decide(self, approved: bool, approver: str = "", note: str = "") -> None:
        if self._decided is None:
            self._decided = approved
            self._approver = approver
            self._note = note
            self._via = "human"

    @workflow.query
    def pending(self) -> dict:
        """Open approval request (for a UI/CLI), or {"pending": False}."""
        return self._pending or {"pending": False}

    async def _approval_gate(self, req: OrderWorkflowInput, discount: float) -> dict:
        details = f"Requested discount {discount}% exceeds threshold {req.discount_threshold}%."
        if req.hitl_mode == "child":
            child = await workflow.execute_child_workflow(
                ApprovalWorkflow.run,
                ApprovalWorkflowInput(
                    reason="discount-approval",
                    discount=discount,
                    threshold=req.discount_threshold,
                    details=details,
                    timeout_seconds=req.approval_timeout_seconds,
                    on_timeout=req.on_timeout,
                ),
                id=f"{workflow.info().workflow_id}-approval",
            )
            return child

        # inline gate
        self._pending = {
            "pending": True,
            "reason": "discount-approval",
            "discount": discount,
            "threshold": req.discount_threshold,
            "details": details,
        }
        try:
            await workflow.wait_condition(
                lambda: self._decided is not None,
                timeout=timedelta(seconds=req.approval_timeout_seconds),
            )
        except asyncio.TimeoutError:
            pass
        self._pending = None
        if self._decided is None:
            self._decided = req.on_timeout == "approve"
            self._via = "timeout"
            self._note = f"auto-{req.on_timeout} on timeout"
        return {
            "approved": self._decided,
            "approver": self._approver,
            "note": self._note,
            "via": self._via,
        }

    @workflow.run
    async def run(self, req: OrderWorkflowInput) -> dict:
        app = graph(req.graph_name).compile()
        result = await app.ainvoke({"request": req.request, "chaos": req.chaos})
        out = {stage: result.get(stage, "") for stage in _STAGES}
        # Incident (if any) is opened by the fulfillment agent itself via A2A.
        out["incident"] = result.get("incident")

        discount = parse_discount(req.request)
        forced = bool(req.chaos.get("force_hitl"))
        required = req.hitl_enabled and (needs_approval(discount, req.discount_threshold) or forced)
        if required:
            decision = await self._approval_gate(req, float(discount or 0.0))
        else:
            decision = {"approved": True, "approver": "", "note": "", "via": "auto"}

        out["approval"] = {
            "required": required,
            "discount": discount,
            "threshold": req.discount_threshold,
            **decision,
        }
        return out
