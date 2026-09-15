"""Local infrastructure lifecycle and health checks.

Responsibilities:

* health-check the services the app depends on (Temporal, OTel collector,
  Prometheus, Grafana) using plain TCP / HTTP probes (no extra deps);
* optionally bring the Docker Compose stack up when ``auto_start`` is set and
  the services are not already reachable (never blindly duplicates containers);
* expose ``up`` / ``down`` / ``status`` for the infrastructure entrypoint.

The worker never stops infrastructure on exit — lifecycle is independent.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from app.config.models import AppSettings

_TCP_TIMEOUT = 2.0
_HTTP_TIMEOUT = 3.0


class DockerUnavailableError(RuntimeError):
    """Raised when Docker/Compose is required but not available."""


class InfrastructureUnavailableError(RuntimeError):
    """Raised when required services are not reachable and cannot be started."""


@dataclass
class ServiceCheck:
    name: str
    ok: bool
    detail: str


def _host_port(target: str) -> tuple[str, int]:
    """Split ``host:port`` (also accepts a URL) into host and port."""
    if "://" in target:
        parsed = urlparse(target)
        return parsed.hostname or "localhost", parsed.port or (443 if parsed.scheme == "https" else 80)
    host, _, port = target.partition(":")
    return host or "localhost", int(port or 0)


def _tcp_ok(target: str) -> bool:
    host, port = _host_port(target)
    try:
        with socket.create_connection((host, port), timeout=_TCP_TIMEOUT):
            return True
    except OSError:
        return False


def _http_ok(url: str) -> bool:
    try:
        with urlopen(url, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310 - internal URLs
            return 200 <= resp.status < 300
    except (URLError, OSError, ValueError):
        return False


def _required_checks(settings: AppSettings, *, worker_only: bool) -> list[ServiceCheck]:
    infra = settings.infrastructure
    obs = settings.observability
    checks: list[ServiceCheck] = []

    # Only health-check a *local* Temporal; in cloud mode connectivity is the
    # client's concern and there is no local container to manage.
    if infra.services.temporal and settings.temporal.mode.value == "self_hosted":
        ok = _tcp_ok(settings.temporal.self_hosted.address)
        checks.append(ServiceCheck("temporal", ok, settings.temporal.self_hosted.address))

    if infra.services.otel_collector and obs.enabled and obs.otel.enabled:
        ok = _tcp_ok(obs.otel.endpoint)
        checks.append(ServiceCheck("otel_collector", ok, obs.otel.endpoint))

    # Prometheus and Grafana are the observability *backend*, downstream of the
    # collector. They are not runtime dependencies of the worker, so they are
    # skipped when checking only what the worker needs to start.
    if not worker_only:
        if infra.services.prometheus:
            ok = _http_ok(infra.prometheus_url.rstrip("/") + "/-/healthy")
            checks.append(ServiceCheck("prometheus", ok, infra.prometheus_url))

        if infra.services.grafana:
            ok = _http_ok(infra.grafana_url.rstrip("/") + "/api/health")
            checks.append(ServiceCheck("grafana", ok, infra.grafana_url))

    return checks


def check_services(settings: AppSettings, *, worker_only: bool = False) -> list[ServiceCheck]:
    """Run health checks and return their results.

    ``worker_only`` limits the checks to the worker's own dependencies (Temporal
    and, when observability is on, the OTel collector).
    """
    return _required_checks(settings, worker_only=worker_only)


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _compose(settings: AppSettings, *args: str) -> subprocess.CompletedProcess:
    if not _docker_available():
        raise DockerUnavailableError(
            "docker is not installed or not on PATH; cannot manage infrastructure"
        )
    cmd = ["docker", "compose", "-f", settings.infrastructure.docker_compose_file, *args]
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def compose_up(settings: AppSettings) -> None:
    result = _compose(settings, "up", "-d")
    if result.returncode != 0:
        raise DockerUnavailableError(f"'docker compose up' failed:\n{result.stderr}")


def compose_down(settings: AppSettings) -> None:
    result = _compose(settings, "down")
    if result.returncode != 0:
        raise DockerUnavailableError(f"'docker compose down' failed:\n{result.stderr}")


async def wait_until_healthy(
    settings: AppSettings, timeout: int, *, worker_only: bool = False
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        checks = check_services(settings, worker_only=worker_only)
        if all(c.ok for c in checks):
            return
        if time.monotonic() >= deadline:
            unhealthy = ", ".join(c.name for c in checks if not c.ok)
            raise InfrastructureUnavailableError(
                f"infrastructure did not become healthy within {timeout}s: {unhealthy}"
            )
        await asyncio.sleep(2)


async def ensure_infrastructure(settings: AppSettings) -> None:
    """Ensure required services are reachable before the worker starts.

    * If everything is already reachable, do nothing.
    * If ``auto_start`` is enabled, bring Compose up and wait for health.
    * If ``auto_start`` is disabled, fail clearly (no Docker commands run).
    """
    checks = check_services(settings, worker_only=True)
    missing = [c for c in checks if not c.ok]
    if not missing:
        return

    infra = settings.infrastructure
    if not infra.auto_start:
        names = ", ".join(f"{c.name} ({c.detail})" for c in missing)
        raise InfrastructureUnavailableError(
            f"required services unavailable and auto_start=false: {names}"
        )

    compose_up(settings)
    await wait_until_healthy(settings, infra.startup_timeout_seconds, worker_only=True)
