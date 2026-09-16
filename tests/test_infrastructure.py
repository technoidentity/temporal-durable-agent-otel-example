"""Infrastructure health checks and Docker gating (all mocked, no real services)."""

import pytest

from app.config.models import AppSettings, InfrastructureConfig
from app.infrastructure import docker as infra
from app.infrastructure.docker import InfrastructureUnavailableError, ensure_infrastructure


def test_host_port_parsing():
    assert infra._host_port("localhost:7233") == ("localhost", 7233)
    assert infra._host_port("http://otel:4317") == ("otel", 4317)
    assert infra._host_port("https://grafana:3000") == ("grafana", 3000)


def test_check_services_reports_status(monkeypatch):
    monkeypatch.setattr(infra, "_tcp_ok", lambda target: True)
    monkeypatch.setattr(infra, "_http_ok", lambda url: False)
    settings = AppSettings()
    checks = {c.name: c.ok for c in infra.check_services(settings)}
    assert checks["temporal"] is True  # tcp
    assert checks["prometheus"] is False  # http
    assert checks["grafana"] is False


def test_worker_only_excludes_backend(monkeypatch):
    monkeypatch.setattr(infra, "_tcp_ok", lambda target: True)
    monkeypatch.setattr(infra, "_http_ok", lambda url: True)
    names = {c.name for c in infra.check_services(AppSettings(), worker_only=True)}
    assert names == {"temporal", "otel_collector"}
    assert "prometheus" not in names and "grafana" not in names


async def test_ensure_infra_noop_when_all_healthy(monkeypatch):
    monkeypatch.setattr(infra, "_tcp_ok", lambda target: True)
    monkeypatch.setattr(infra, "_http_ok", lambda url: True)
    called = {"up": False}
    monkeypatch.setattr(infra, "compose_up", lambda s: called.__setitem__("up", True))
    await ensure_infrastructure(AppSettings())
    assert called["up"] is False  # nothing started


async def test_ensure_infra_fails_clearly_when_autostart_off(monkeypatch):
    monkeypatch.setattr(infra, "_tcp_ok", lambda target: False)
    monkeypatch.setattr(infra, "_http_ok", lambda url: False)
    called = {"up": False}
    monkeypatch.setattr(infra, "compose_up", lambda s: called.__setitem__("up", True))
    settings = AppSettings(infrastructure=InfrastructureConfig(auto_start=False))
    with pytest.raises(InfrastructureUnavailableError):
        await ensure_infrastructure(settings)
    assert called["up"] is False  # no docker command executed
