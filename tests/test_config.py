"""Config parsing, env overrides, and validation."""

import textwrap

import pytest

from app.config.loader import load_settings
from app.config.models import AppSettings, TemporalMode


def _write(tmp_path, body: str):
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(body))
    return path


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no config/ present
    settings = load_settings(load_env_file=False)
    assert settings.temporal.mode is TemporalMode.self_hosted
    assert settings.temporal.address == "localhost:7233"
    assert settings.temporal.task_queue == "langgraph-agent"


def test_yaml_overrides_defaults(tmp_path):
    path = _write(
        tmp_path,
        """
        temporal:
          task_queue: from-yaml
          self_hosted:
            address: host.yaml:7233
        """,
    )
    settings = load_settings(path, load_env_file=False)
    assert settings.temporal.task_queue == "from-yaml"
    assert settings.temporal.self_hosted.address == "host.yaml:7233"


def test_env_overrides_yaml(tmp_path, monkeypatch):
    path = _write(tmp_path, "temporal:\n  task_queue: from-yaml\n")
    monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "from-env")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    settings = load_settings(path, load_env_file=False)
    assert settings.temporal.task_queue == "from-env"
    assert settings.observability.otel.endpoint == "http://collector:4317"


def test_env_interpolation_in_yaml(tmp_path, monkeypatch):
    path = _write(tmp_path, "llm:\n  api_key: ${OPENAI_API_KEY}\n")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    settings = load_settings(path, load_env_file=False)
    assert settings.llm.api_key == "sk-test-123"


def test_bool_coercion_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INFRA_AUTO_START", "false")
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "0")
    settings = load_settings(load_env_file=False)
    assert settings.infrastructure.auto_start is False
    assert settings.observability.enabled is False


def test_extra_keys_rejected():
    with pytest.raises(Exception):
        AppSettings.model_validate({"unknown_section": {}})
