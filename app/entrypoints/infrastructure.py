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
from app.temporal.client import create_temporal_client

# Typed Search Attributes the workflows upsert when
# temporal.search_attributes_enabled is on (review L2). Register once per
# namespace before enabling the flag, or the server rejects the upsert.
_SEARCH_ATTRIBUTES = {
    "PepsicoApprovalPending": "Bool",
    "PepsicoApprovalReason": "Keyword",
}


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


@cli.command("register-search-attributes")
def register_search_attributes() -> None:
    """Register the pending-approval Search Attributes on the namespace (L2)."""
    from temporalio.api.enums.v1 import IndexedValueType
    from temporalio.api.operatorservice.v1 import AddSearchAttributesRequest

    settings = load_settings()
    types = {
        "Bool": IndexedValueType.INDEXED_VALUE_TYPE_BOOL,
        "Keyword": IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD,
    }

    async def _register() -> None:
        client = await create_temporal_client(settings)
        try:
            await client.operator_service.add_search_attributes(
                AddSearchAttributesRequest(
                    namespace=settings.temporal.namespace,
                    search_attributes={n: types[t] for n, t in _SEARCH_ATTRIBUTES.items()},
                )
            )
            click.echo(f"Registered: {', '.join(_SEARCH_ATTRIBUTES)}")
        except Exception as exc:  # already-exists is fine; report anything else
            if "already exist" in str(exc).lower():
                click.echo("Search attributes already registered.")
            else:
                raise

    asyncio.run(_register())


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
