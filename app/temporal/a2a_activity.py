"""Temporal activity that performs an A2A call (nondeterministic HTTP)."""

from __future__ import annotations

from dataclasses import dataclass

from temporalio import activity

from app.platform.a2a import A2AClient


@dataclass
class A2ACallInput:
    target_url: str
    message: str
    context_id: str | None = None
    timeout_seconds: float = 30.0


@activity.defn
async def a2a_call_activity(inp: A2ACallInput) -> str:
    client = A2AClient(timeout_seconds=inp.timeout_seconds)
    result = await client.send(inp.target_url, inp.message, inp.context_id)
    return result.result
