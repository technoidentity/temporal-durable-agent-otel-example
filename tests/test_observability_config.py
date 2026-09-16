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


def test_phoenix_config_defaults():
    obs = ObservabilityConfig()
    assert obs.phoenix.enabled is False
    assert obs.phoenix.endpoint.endswith(":6006")
    assert obs.instrument_llm is False


def test_init_telemetry_disabled_is_noop():
    from app.config.models import AppSettings
    from app.observability.telemetry import init_telemetry

    settings = AppSettings.model_validate({"observability": {"enabled": False}})
    handle = init_telemetry(settings)
    assert handle.tracer_provider is None
    assert handle.meter_provider is None
    handle.shutdown()  # must not raise


def test_arize_config_and_resource():
    from app.config.models import AppSettings
    from app.observability.telemetry import _arize_traces_url, build_resource

    assert _arize_traces_url("https://otlp.arize.com/v1") == "https://otlp.arize.com/v1/traces"
    assert _arize_traces_url("https://otlp.arize.com/v1/traces") == "https://otlp.arize.com/v1/traces"
    assert _arize_traces_url("https://x/") == "https://x/v1/traces"

    s = AppSettings.model_validate(
        {"observability": {"arize": {"enabled": True, "project_name": "demo", "space_id": "s", "api_key": "k"}}}
    )
    attrs = build_resource(s).attributes
    assert attrs["openinference.project.name"] == "demo"
    assert s.observability.arize.transport == "app"
