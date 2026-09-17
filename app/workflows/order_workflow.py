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
from temporalio.common import RetryPolicy, SearchAttributeKey, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from temporalio.contrib.langgraph import graph

    from app.integrations.servicenow import detect_risk
    from app.platform.hitl import needs_approval, parse_discount
    from app.temporal.a2a_activity import A2ACallInput, a2a_call_activity
    from app.workflows.approval_workflow import ApprovalWorkflow, ApprovalWorkflowInput

_STAGES = ("intake", "inventory", "pricing", "fulfillment", "account", "outcome")

# Typed Search Attributes for pending approvals (review L2). Registered on the
# namespace out-of-band; upserted only when temporal.search_attributes_enabled.
APPROVAL_PENDING = SearchAttributeKey.for_bool("PepsicoApprovalPending")
APPROVAL_REASON = SearchAttributeKey.for_keyword("PepsicoApprovalReason")


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
    # Emit typed Search Attributes while the gate is open (review L2).
    search_attributes_enabled: bool = False


@workflow.defn
class OrderWorkflow:
    def __init__(self) -> None:
        self._decided: bool | None = None
        self._approver: str = ""
        self._note: str = ""
        self._via: str = ""
        self._pending: dict | None = None

    def _record(self, approved: bool, approver: str, note: str) -> None:
        """First-wins recording shared by the signal and the update (L1)."""
        if self._decided is None:
            self._decided = approved
            self._approver = approver
            self._note = note
            self._via = "human"

    @workflow.signal
    def decide(self, approved: bool, approver: str = "", note: str = "") -> None:
        self._record(approved, approver, note)

    @workflow.update
    def decide_update(self, approved: bool, approver: str = "", note: str = "") -> dict:
        """Update-based gate (review L1): confirms the decision atomically and,
        via the validator, rejects a decision when no gate is open or one was
        already made — unlike the fire-and-forget signal."""
        self._record(approved, approver, note)
        return {"approved": self._decided, "approver": self._approver,
                "note": self._note, "via": self._via}

    @decide_update.validator
    def _validate_decide(self, approved: bool, approver: str = "", note: str = "") -> None:
        if self._decided is not None:
            raise ApplicationError("Order approval already decided", non_retryable=True)
        if not (self._pending or {}).get("pending"):
            raise ApplicationError("Order is not awaiting approval", non_retryable=True)

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
                    search_attributes_enabled=req.search_attributes_enabled,
                ),
                id=f"{workflow.info().workflow_id}-approval",
                # Explicit policies (review M4): the child must be able to wait the
                # full approval window, a human gate should not be retried, and the
                # id is deterministic so a duplicate parent cannot fork the gate.
                execution_timeout=timedelta(seconds=req.approval_timeout_seconds + 300),
                retry_policy=RetryPolicy(maximum_attempts=1),
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                parent_close_policy=workflow.ParentClosePolicy.TERMINATE,
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
        if req.search_attributes_enabled:
            workflow.upsert_search_attributes(
                [APPROVAL_PENDING.value_set(True), APPROVAL_REASON.value_set("discount-approval")]
            )
        try:
            await workflow.wait_condition(
                lambda: self._decided is not None,
                timeout=timedelta(seconds=req.approval_timeout_seconds),
            )
        except asyncio.TimeoutError:
            pass
        self._pending = None
        if req.search_attributes_enabled:
            workflow.upsert_search_attributes([APPROVAL_PENDING.value_set(False)])
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

        # Third-party leg (review B3): a dedicated, idempotency-keyed activity —
        # NOT fused with the LLM node — opens the ServiceNow incident on risk.
        # The deterministic context id makes retries safe (the server upserts).
        #
        # Gated behind a patch marker (review M2): this activity was added after
        # the workflow first shipped, so `workflow.patched` keeps histories from
        # runs that predate it replaying deterministically. Once every pre-patch
        # run has drained, collapse this to `workflow.deprecate_patch(...)`.
        out["incident"] = None
        fulfillment_text = out.get("fulfillment", "")
        if (
            workflow.patched("order-servicenow-incident-leg")
            and req.servicenow_a2a_url
            and req.open_incident_on_risk
            and detect_risk(fulfillment_text, req.risk_keywords)
        ):
            try:
                out["incident"] = await workflow.execute_activity(
                    a2a_call_activity,
                    A2ACallInput(
                        target_url=req.servicenow_a2a_url,
                        message=(
                            "Open incident for fulfillment risk. "
                            f"Order: {req.request} | Fulfillment: {fulfillment_text[:400]}"
                        ),
                        context_id=f"{workflow.info().workflow_id}-servicenow",
                        timeout_seconds=30.0,
                    ),
                    start_to_close_timeout=timedelta(seconds=45),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except Exception as exc:  # keep the order resilient to the 3rd-party call
                out["incident"] = f"incident-error: {exc}"
        return out
