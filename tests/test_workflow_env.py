"""End-to-end workflow tests through a real Temporal test server + the LangGraph
plugin (review M1). These exercise the payload boundary and the approval gate,
which unit tests that call ``ainvoke`` outside Temporal cannot.

Skipped automatically if the Temporal test-server binary can't be started
(e.g. no network to download it); run in CI where it can.
"""

import asyncio

import pytest
from temporalio.contrib.langgraph import LangGraphPlugin
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.agent.multi import build_order_graph
from app.config.models import AppSettings, HITLConfig, LLMConfig, LLMProvider, MultiAgentConfig
from app.temporal.a2a_activity import a2a_call_activity
from app.workflows.approval_workflow import ApprovalWorkflow
from app.workflows.order_workflow import OrderWorkflow, OrderWorkflowInput

TASK_QUEUE = "test-order"


def _settings(threshold: float = 15.0) -> AppSettings:
    return AppSettings(
        llm=LLMConfig(provider=LLMProvider.fake),
        multi_agent=MultiAgentConfig(enabled=True),
        hitl=HITLConfig(enabled=True, discount_threshold=threshold, approval_timeout_seconds=3600),
    )


async def _worker(env, settings):
    plugin = LangGraphPlugin(graphs={settings.multi_agent.graph_name: build_order_graph(settings)})
    return Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[OrderWorkflow, ApprovalWorkflow],
        activities=[a2a_call_activity],
        plugins=[plugin],
    )


async def _start_env():
    try:
        return await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:  # binary unavailable / no network
        pytest.skip(f"Temporal test server unavailable: {exc}")


async def test_gated_order_approves_and_completes():
    settings = _settings()
    env = await _start_env()
    async with env:
        async with await _worker(env, settings):
            handle = await env.client.start_workflow(
                OrderWorkflow.run,
                OrderWorkflowInput(
                    request="Star Distributors: 500 cases at 20% discount",
                    graph_name=settings.multi_agent.graph_name,
                    discount_threshold=15.0,
                ),
                id="wf-gate",
                task_queue=TASK_QUEUE,
            )
            pending = {"pending": False}
            for _ in range(100):
                pending = await handle.query(OrderWorkflow.pending)
                if pending.get("pending"):
                    break
                await asyncio.sleep(0.05)
            assert pending["pending"] is True  # gate fired (B1/B2 regression home)

            await handle.signal(OrderWorkflow.decide, args=[True, "tester", "ok"])
            result = await handle.result()
            assert result["approval"]["approved"] is True
            assert result["approval"]["via"] == "human"
            # Messages crossed the real payload boundary (H3) without error.
            assert result["outcome"]


async def test_below_threshold_auto_approves():
    settings = _settings()
    env = await _start_env()
    async with env:
        async with await _worker(env, settings):
            result = await env.client.execute_workflow(
                OrderWorkflow.run,
                OrderWorkflowInput(
                    request="Metro Foods: 200 cases at 10% discount",
                    graph_name=settings.multi_agent.graph_name,
                    discount_threshold=15.0,
                ),
                id="wf-auto",
                task_queue=TASK_QUEUE,
            )
            assert result["approval"]["required"] is False
            assert result["approval"]["via"] == "auto"
