import os
import sys
from pathlib import Path

import pytest

# Make the project importable without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# These override variables leak between tests unless cleared; the loader reads
# them from os.environ, so isolate each test from the developer's shell/.env.
_MANAGED_ENV = [
    "TEMPORAL_MODE",
    "TEMPORAL_ADDRESS",
    "TEMPORAL_NAMESPACE",
    "TEMPORAL_TASK_QUEUE",
    "TEMPORAL_CLOUD_ADDRESS",
    "TEMPORAL_CLOUD_NAMESPACE",
    "TEMPORAL_CLOUD_API_KEY",
    "OPENAI_API_KEY",
    "LLM_PROVIDER",
    "OBSERVABILITY_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "TEMPORAL_CLOUD_METRICS_ENABLED",
    "TEMPORAL_METRICS_API_KEY",
    "INFRA_AUTO_START",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _MANAGED_ENV:
        monkeypatch.delenv(name, raising=False)
    yield
