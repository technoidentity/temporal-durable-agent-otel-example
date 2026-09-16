"""Single Temporal client abstraction for self-hosted and Temporal Cloud.

Both modes go through :func:`create_temporal_client`; the only difference is the
address/namespace/TLS/API-key resolved from config. No client initialization
logic is duplicated anywhere else.
"""

from __future__ import annotations

from temporalio.client import Client
from temporalio.runtime import Runtime

from app.config.models import AppSettings, TemporalMode


async def create_temporal_client(
    settings: AppSettings,
    *,
    runtime: Runtime | None = None,
    interceptors: list | None = None,
    plugins: list | None = None,
) -> Client:
    """Connect to Temporal using the mode selected in config.

    - ``self_hosted``: plaintext connection to e.g. ``localhost:7233``.
    - ``cloud``: TLS + API-key auth to ``<namespace>.<account>.tmprl.cloud:7233``.
    """
    temporal = settings.temporal

    connect_kwargs: dict = {
        "target_host": temporal.address,
        "namespace": temporal.namespace,
        "interceptors": interceptors or [],
    }
    if runtime is not None:
        connect_kwargs["runtime"] = runtime
    if plugins:
        connect_kwargs["plugins"] = plugins

    if temporal.mode is TemporalMode.cloud:
        connect_kwargs["api_key"] = temporal.cloud.api_key
        # API-key auth to Temporal Cloud requires TLS.
        connect_kwargs["tls"] = temporal.cloud.tls_enabled

    return await Client.connect(**connect_kwargs)
