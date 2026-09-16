"""Chaos fault injection logic and config."""

import pytest

from app.config.models import AppSettings, ChaosConfig
from app.platform.chaos import ChaosError, maybe_inject


def test_no_chaos_is_noop():
    assert maybe_inject("inventory", None) is None
    assert maybe_inject("inventory", {}) is None
    assert maybe_inject("inventory", {"target": "pricing", "mode": "permanent_error"}) is None


def test_permanent_error_raises_for_target():
    with pytest.raises(ChaosError):
        maybe_inject("inventory", {"target": "inventory", "mode": "permanent_error", "attempts": 0})


def test_transient_error_first_attempt(monkeypatch):
    import app.platform.chaos as mod

    monkeypatch.setattr(mod, "_current_attempt", lambda: 1)
    with pytest.raises(ChaosError):
        maybe_inject("inventory", {"target": "inventory", "mode": "transient_error", "attempts": 1})


def test_transient_error_recovers_on_retry(monkeypatch):
    import app.platform.chaos as mod

    monkeypatch.setattr(mod, "_current_attempt", lambda: 2)  # second attempt
    # attempts=1 -> only attempt 1 fails; attempt 2 passes.
    assert maybe_inject("inventory", {"target": "inventory", "mode": "transient_error", "attempts": 1}) is None


def test_latency_sleeps_and_reports():
    slept = {}
    action = maybe_inject(
        "pricing",
        {"target": "pricing", "mode": "latency", "attempts": 0, "latency_seconds": 0.01},
        sleep=lambda s: slept.setdefault("s", s),
    )
    assert action == "latency"
    assert slept["s"] == 0.01


def test_chaos_config_as_spec():
    assert ChaosConfig().as_spec() == {}
    spec = ChaosConfig(enabled=True, target="inventory", mode="transient_error").as_spec()
    assert spec["target"] == "inventory"
    assert spec["mode"] == "transient_error"
    assert AppSettings().chaos.enabled is False
