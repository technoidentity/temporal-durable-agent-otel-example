"""Worker entry point.

    python -m app.entrypoints.worker

Flow: load config -> ensure infrastructure -> init OTel -> create runtime ->
connect Temporal -> build LangGraph -> register plugin -> start Worker, and
shut down cleanly on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import signal

from temporalio.contrib.langgraph import LangGraphPlugin
from temporalio.worker import Worker

from app.agent.graph import build_graph
from app.config import load_settings
from app.config.models import AppSettings
from app.infrastructure.docker import ensure_infrastructure
from app.observability import (
    build_temporal_interceptors,
    configure_logging,
    init_telemetry,
)
from app.temporal.client import create_temporal_client
from app.temporal.retry import build_activity_options
from app.temporal.runtime import create_runtime
from app.workflows.agent_workflow import AgentWorkflow


async def run_worker(settings: AppSettings) -> None:
    log = configure_logging(settings)
    log.info("worker.starting", mode=settings.temporal.mode.value)

    await ensure_infrastructure(settings)
    log.info("infrastructure.ready")

    telemetry = init_telemetry(settings)
    runtime = create_runtime(settings)
    interceptors = build_temporal_interceptors(settings)

    graph = build_graph(settings)
    plugin = LangGraphPlugin(
        graphs={settings.langgraph.graph_name: graph},
        default_activity_options=build_activity_options(settings.temporal.activity),
    )

    client = await create_temporal_client(
        settings, runtime=runtime, interceptors=interceptors
    )
    log.info(
        "temporal.connected",
        address=settings.temporal.address,
        namespace=settings.temporal.namespace,
    )

    worker = Worker(
        client,
        task_queue=settings.temporal.task_queue,
        workflows=[AgentWorkflow],
        plugins=[plugin],
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - non-unix
            pass

    log.info("worker.running", task_queue=settings.temporal.task_queue)
    try:
        async with worker:
            await stop.wait()
    finally:
        log.info("worker.stopping")
        telemetry.shutdown()


def main() -> None:
    settings = load_settings()
    asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
