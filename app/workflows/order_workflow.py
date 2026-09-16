"""Durable Temporal workflow for the PepsiCo multi-agent order pipeline.

Deterministic: it only invokes the registered graph with a serializable input.
The nondeterministic agent reasoning runs in Activities via the LangGraph plugin.
"""

from __future__ import annotations

from dataclasses import dataclass

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from temporalio.contrib.langgraph import graph

_STAGES = ("intake", "inventory", "pricing", "fulfillment", "account", "outcome")


@dataclass
class OrderWorkflowInput:
    request: str
    graph_name: str


@workflow.defn
class OrderWorkflow:
    @workflow.run
    async def run(self, req: OrderWorkflowInput) -> dict:
        app = graph(req.graph_name).compile()
        result = await app.ainvoke({"request": req.request})
        return {stage: result.get(stage, "") for stage in _STAGES}
