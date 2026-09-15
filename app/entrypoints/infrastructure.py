"""Infrastructure lifecycle entry point.

    python -m app.entrypoints.infrastructure up
    python -m app.entrypoints.infrastructure down
    python -m app.entrypoints.infrastructure status

Lifecycle is independent of the worker: the worker never stops infrastructure.
"""

from __future__ import annotations

import asyncio

import click

from app.config import load_settings
from app.infrastructure.docker import (
    check_services,
    compose_down,
    compose_up,
    wait_until_healthy,
)


@click.group()
def cli() -> None:
    """Manage local infrastructure (Temporal, OTel, Prometheus, Grafana)."""


@cli.command("up")
def up() -> None:
    settings = load_settings()
    # `up` forces a start regardless of auto_start, then waits for health.
    compose_up(settings)
    asyncio.run(wait_until_healthy(settings, settings.infrastructure.startup_timeout_seconds))
    click.echo("Infrastructure is up and healthy.")


@cli.command("down")
def down() -> None:
    settings = load_settings()
    compose_down(settings)
    click.echo("Infrastructure stopped.")


@cli.command("status")
def status() -> None:
    settings = load_settings()
    checks = check_services(settings)
    for c in checks:
        mark = "OK " if c.ok else "DOWN"
        click.echo(f"[{mark}] {c.name:<16} {c.detail}")
    if not all(c.ok for c in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
