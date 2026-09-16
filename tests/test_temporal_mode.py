"""Temporal mode selection and cloud/self-hosted validation."""

import pytest
from pydantic import ValidationError

from app.config.models import (
    AppSettings,
    CloudConfig,
    TemporalConfig,
    TemporalMode,
)


def test_self_hosted_resolves_address_and_namespace():
    cfg = TemporalConfig(mode=TemporalMode.self_hosted)
    assert cfg.address == "localhost:7233"
    assert cfg.namespace == "default"


def test_cloud_requires_credentials():
    with pytest.raises(ValidationError) as exc:
        TemporalConfig(mode=TemporalMode.cloud)
    msg = str(exc.value)
    assert "temporal.cloud.address" in msg
    assert "temporal.cloud.api_key" in msg


def test_cloud_valid_resolves_cloud_values():
    cfg = TemporalConfig(
        mode=TemporalMode.cloud,
        cloud=CloudConfig(
            address="ns.acct.tmprl.cloud:7233",
            namespace="ns.acct",
            api_key="secret",
        ),
    )
    assert cfg.address == "ns.acct.tmprl.cloud:7233"
    assert cfg.namespace == "ns.acct"
    assert cfg.cloud.tls_enabled is True


def test_mode_switch_is_config_only():
    # Same object shape; only mode + cloud creds differ.
    settings = AppSettings.model_validate(
        {
            "temporal": {
                "mode": "cloud",
                "cloud": {
                    "address": "ns.acct.tmprl.cloud:7233",
                    "namespace": "ns.acct",
                    "api_key": "k",
                },
            }
        }
    )
    assert settings.temporal.mode is TemporalMode.cloud
