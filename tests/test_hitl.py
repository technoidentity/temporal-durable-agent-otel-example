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
