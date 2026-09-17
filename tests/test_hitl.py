"""HITL gate logic (deterministic) and config."""

import pytest

from app.config.models import AppSettings, HITLMode, OnTimeout
from app.platform.hitl import needs_approval, parse_discount


@pytest.mark.parametrize(
    "text,expected",
    [
        ("500 cases, 20% discount", 20.0),
        ("no discount here", None),
        ("10% now, later 25% promo", 25.0),  # highest wins
        ("discount of 12.5%", 12.5),
    ],
)
def test_parse_discount(text, expected):
    assert parse_discount(text) == expected


@pytest.mark.parametrize(
    "discount,threshold,expected",
    [
        (20.0, 15.0, True),
        (15.0, 15.0, False),  # strictly greater
        (10.0, 15.0, False),
        (None, 15.0, False),
    ],
)
def test_needs_approval(discount, threshold, expected):
    assert needs_approval(discount, threshold) is expected


def test_hitl_config_defaults():
    h = AppSettings().hitl
    assert h.enabled is True
    assert h.mode is HITLMode.inline
    assert h.discount_threshold == 15.0
    assert h.on_timeout is OnTimeout.reject


def test_hitl_config_overridable():
    s = AppSettings.model_validate(
        {"hitl": {"discount_threshold": 5, "approval_timeout_seconds": 60, "mode": "child"}}
    )
    assert s.hitl.discount_threshold == 5
    assert s.hitl.approval_timeout_seconds == 60
    assert s.hitl.mode is HITLMode.child


def test_update_gate_validator_and_first_wins():
    """Review L1: the update validator rejects a decision when no gate is open or
    one was already made; the shared recorder keeps the first decision."""
    from temporalio.exceptions import ApplicationError
    from app.workflows.order_workflow import OrderWorkflow

    wf = OrderWorkflow()
    # No gate open -> rejected.
    with pytest.raises(ApplicationError):
        wf._validate_decide(True, "op", "")

    wf._pending = {"pending": True}
    wf._validate_decide(True, "op", "ok")  # gate open -> allowed
    out = wf.decide_update(True, "op", "ok")
    assert out == {"approved": True, "approver": "op", "note": "ok", "via": "human"}

    # Already decided -> rejected, and a late signal cannot flip it (first-wins).
    with pytest.raises(ApplicationError):
        wf._validate_decide(False, "x", "")
    wf.decide(False, "late", "no")
    assert wf._decided is True and wf._approver == "op"


def test_approval_workflow_update_validator():
    from temporalio.exceptions import ApplicationError
    from app.workflows.approval_workflow import ApprovalWorkflow, ApprovalWorkflowInput

    wf = ApprovalWorkflow()
    with pytest.raises(ApplicationError):  # run() not started -> no request yet
        wf._validate_decide(True, "op", "")

    wf._req = ApprovalWorkflowInput(reason="discount-approval", discount=20.0, threshold=15.0)
    wf._validate_decide(True, "op", "ok")
    assert wf.decide_update(False, "op", "")["approved"] is False


def test_execution_timeout_must_exceed_approval():
    import pytest
    from app.config.models import AppSettings
    # gate wait >= execution timeout is rejected (review B1)
    with pytest.raises(Exception):
        AppSettings.model_validate({
            "temporal": {"workflow": {"execution_timeout_seconds": 300}},
            "hitl": {"approval_timeout_seconds": 86400},
        })
    # valid when execution comfortably exceeds the gate
    ok = AppSettings.model_validate({
        "temporal": {"workflow": {"execution_timeout_seconds": 604800}},
        "hitl": {"approval_timeout_seconds": 86400},
    })
    assert ok.temporal.workflow.execution_timeout_seconds == 604800
