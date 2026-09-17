"""Configuration loader.

Assembles :class:`AppSettings` from three layers, highest precedence first:

    1. environment variables (explicit names, see ``_ENV_OVERRIDES``)
    2. a YAML config file (with ``${VAR}`` interpolation from the environment)
    3. safe defaults declared on the Pydantic models

The YAML is the base document; explicit environment variables are layered on
top of it before validation. This keeps secrets out of YAML while allowing the
whole nested tree to be overridden from the environment for containers/CI.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from app.config.models import AppSettings

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")

# Explicit, documented environment overrides -> path in the settings tree.
# Value is a dotted path into the nested config dict.
_ENV_OVERRIDES: dict[str, str] = {
    # app
    "APP_NAME": "app.name",
    "APP_ENVIRONMENT": "app.environment",
    "ENVIRONMENT": "app.environment",
    # temporal
    "TEMPORAL_MODE": "temporal.mode",
    "TEMPORAL_TASK_QUEUE": "temporal.task_queue",
    "TEMPORAL_ADDRESS": "temporal.self_hosted.address",
    "TEMPORAL_NAMESPACE": "temporal.self_hosted.namespace",
    "TEMPORAL_CLOUD_ADDRESS": "temporal.cloud.address",
    "TEMPORAL_CLOUD_NAMESPACE": "temporal.cloud.namespace",
    "TEMPORAL_CLOUD_API_KEY": "temporal.cloud.api_key",
    "TEMPORAL_CLOUD_TLS_ENABLED": "temporal.cloud.tls_enabled",
    "TEMPORAL_SEARCH_ATTRIBUTES_ENABLED": "temporal.search_attributes_enabled",
    # langgraph / multi-agent
    "LANGGRAPH_ENABLED": "langgraph.enabled",
    "LANGGRAPH_GRAPH_NAME": "langgraph.graph_name",
    "MULTI_AGENT_ENABLED": "multi_agent.enabled",
    # llm
    "LLM_PROVIDER": "llm.provider",
    "LLM_MODEL": "llm.model",
    "LLM_BASE_URL": "llm.base_url",
    "OPENAI_API_KEY": "llm.api_key",
    "OPENAI_BASE_URL": "llm.base_url",
    "LYZR_API_KEY": "llm.api_key",
    "LYZR_AGENT_ID": "llm.lyzr_agent_id",
    "LYZR_BASE_URL": "llm.base_url",
    # observability
    "OBSERVABILITY_ENABLED": "observability.enabled",
    "OTEL_SERVICE_NAME": "observability.service_name",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "observability.otel.endpoint",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "observability.otel.protocol",
    "TEMPORAL_CLOUD_METRICS_ENABLED": "observability.temporal_cloud_metrics.enabled",
    "TEMPORAL_METRICS_API_KEY": "observability.temporal_cloud_metrics.api_key",
    # Arize Cloud
    "ARIZE_ENABLED": "observability.arize.enabled",
    "ARIZE_TRANSPORT": "observability.arize.transport",
    "ARIZE_OTLP_ENDPOINT": "observability.arize.endpoint",
    "ARIZE_API_KEY": "observability.arize.api_key",
    "ARIZE_SPACE_ID": "observability.arize.space_id",
    "ARIZE_PROJECT_NAME": "observability.arize.project_name",
    # third-party (ServiceNow)
    "SERVICENOW_MODE": "third_party.servicenow.mode",
    "SERVICENOW_BASE_URL": "third_party.servicenow.base_url",
    "SERVICENOW_USER": "third_party.servicenow.username",
    "SERVICENOW_PASSWORD": "third_party.servicenow.password",
    "SERVICENOW_A2A_URL": "third_party.servicenow.a2a_url",
    # infrastructure
    "INFRA_AUTO_START": "infrastructure.auto_start",
    "INFRA_COMPOSE_FILE": "infrastructure.docker_compose_file",
}

_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


def _interpolate(value: Any) -> Any:
    """Replace ``${VAR}`` tokens in strings with environment values.

    Unset variables collapse to an empty string, which the models then treat as
    "not provided" (and validation catches anything genuinely required).
    """
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


def _coerce(raw: str) -> Any:
    lowered = raw.strip().lower()
    if lowered in _BOOL_TRUE:
        return True
    if lowered in _BOOL_FALSE:
        return False
    return raw


def _set_path(tree: dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    node = tree
    for key in keys[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):  # pragma: no cover - defensive
            raise ValueError(f"config path {dotted!r} collides with a scalar value")
    node[keys[-1]] = value


def _apply_env_overrides(tree: dict[str, Any]) -> dict[str, Any]:
    for env_name, dotted in _ENV_OVERRIDES.items():
        if env_name in os.environ and os.environ[env_name] != "":
            _set_path(tree, dotted, _coerce(os.environ[env_name]))
    return tree


def _default_config_path() -> Path | None:
    for candidate in (
        os.environ.get("APP_CONFIG_FILE"),
        "config/config.yaml",
        "config/config.example.yaml",
    ):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def load_settings(
    config_path: str | os.PathLike[str] | None = None,
    *,
    load_env_file: bool = True,
) -> AppSettings:
    """Build the validated :class:`AppSettings`.

    Args:
        config_path: Explicit YAML path. Falls back to ``APP_CONFIG_FILE`` then
            ``config/config.yaml`` then ``config/config.example.yaml``.
        load_env_file: When true, load a local ``.env`` before reading the
            environment (development convenience; no-op if the file is absent).
    """
    if load_env_file:
        load_dotenv(override=False)

    path = Path(config_path) if config_path else _default_config_path()

    tree: dict[str, Any] = {}
    if path is not None:
        with open(path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"config file {path} must contain a top-level mapping")
        tree = _interpolate(loaded)

    tree = _apply_env_overrides(tree)
    return AppSettings.model_validate(tree)
