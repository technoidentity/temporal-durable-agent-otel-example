"""Observability config toggles and validation."""

import pytest
from pydantic import ValidationError

from app.config.models import ObservabilityConfig, TemporalCloudMetricsConfig


def test_disabled_observability_makes_signals_inactive():
    obs = ObservabilityConfig(enabled=False)
    assert obs.traces_active is False
    assert obs.metrics_active is False
    assert obs.worker_metrics_active is False


def test_signals_active_when_enabled():
    obs = ObservabilityConfig()
    assert obs.traces_active is True
    assert obs.metrics_active is True
    assert obs.worker_metrics_active is True


def test_cloud_metrics_requires_api_key():
    with pytest.raises(ValidationError):
        TemporalCloudMetricsConfig(enabled=True)


def test_cloud_metrics_ok_with_key():
    cfg = TemporalCloudMetricsConfig(enabled=True, api_key="token")
    assert cfg.enabled is True


def test_worker_metrics_inactive_when_metrics_off():
    obs = ObservabilityConfig(metrics={"enabled": False})
    assert obs.worker_metrics_active is False
