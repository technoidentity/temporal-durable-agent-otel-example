"""Worker entry point.

    python -m app.entrypoints.worker

Flow: load config -> ensure infrastructure -> init OTel -> create runtime ->
connect Temporal -> build LangGraph -> register plugin -> start Worker, and
shut down cleanly on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import signal
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio.contrib.langgraph import LangGraphPlugin
from temporalio.worker import Worker

from app.agent.graph import build_graph
from app.agent.multi import build_order_graph
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
from app.workflows.approval_workflow import ApprovalWorkflow
from app.workflows.order_workflow import OrderWorkflow


async def run_worker(settings: AppSettings) -> None:
    log = configure_logging(settings)
    log.info("worker.starting", mode=settings.temporal.mode.value)

    await ensure_infrastructure(settings)
    log.info("infrastructure.ready")

    telemetry = init_telemetry(settings)
    runtime = create_runtime(settings)
    interceptors = build_temporal_interceptors(settings)

    graphs: dict = {}
    workflows: list = []
    if settings.langgraph.enabled:
        graphs[settings.langgraph.graph_name] = build_graph(settings)
        workflows.append(AgentWorkflow)
    if settings.multi_agent.enabled:
        graphs[settings.multi_agent.graph_name] = build_order_graph(settings)
        workflows.extend([OrderWorkflow, ApprovalWorkflow])
        log.info("multi_agent.enabled", graph=settings.multi_agent.graph_name)
    if not graphs:
        raise ValueError("no graphs enabled: enable langgraph and/or multi_agent")

    activities: list = []
    # The order workflow opens ServiceNow incidents via a2a_call_activity, so the
    # activity must be registered whenever multi-agent runs (not only when the
    # standalone A2AWorkflow is enabled).
    if settings.multi_agent.enabled or settings.a2a.enabled:
        from app.temporal.a2a_activity import a2a_call_activity

        activities.append(a2a_call_activity)
    if settings.a2a.enabled:
        from app.workflows.a2a_workflow import A2AWorkflow

        workflows.append(A2AWorkflow)
        log.info("a2a.enabled", agents=list(settings.a2a.agents))

    plugin = LangGraphPlugin(
        graphs=graphs,
        default_activity_options=build_activity_options(settings.temporal.activity),
    )

    # Register the plugin on the CLIENT (review H1); the Worker inherits its
    # client's plugins, so passing it to the Worker as well double-registers the
    # node activities ("More than one activity named ..."). Client-only is the
    # correct single registration.
    client = await create_temporal_client(
        settings, runtime=runtime, interceptors=interceptors, plugins=[plugin]
    )
    log.info(
        "temporal.connected",
        address=settings.temporal.address,
        namespace=settings.temporal.namespace,
    )

    # Sync graph nodes are offloaded to threads; size the pool explicitly and
    # bound activity concurrency so one slow LLM call cannot starve the worker
    # (review H2).
    max_activities = 20
    pool = ThreadPoolExecutor(max_workers=max_activities, thread_name_prefix="activity")
    asyncio.get_running_loop().set_default_executor(pool)

    worker = Worker(
        client,
        task_queue=settings.temporal.task_queue,
        workflows=workflows,
        activities=activities,
        activity_executor=pool,
        max_concurrent_activities=max_activities,
        # Let in-flight activities finish on SIGTERM instead of being cut off and
        # re-run on restart (review H6). Must exceed the longest activity.
        graceful_shutdown_timeout=timedelta(
            seconds=settings.temporal.activity.start_to_close_timeout_seconds + 30
        ),
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
