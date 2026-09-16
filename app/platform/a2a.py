"""Thin, A2A-flavored agent-to-agent protocol (HTTP + JSON).

An A2A agent publishes an *agent card* (capabilities/metadata) and accepts
*tasks* on a message endpoint. This is intentionally small — a pragmatic subset
of the emerging A2A spec — so any agent (including third-party systems like
ServiceNow) can be reached uniformly.

    GET  {base}/.well-known/agent-card.json   -> AgentCard
    POST {base}/a2a/message  {message, context_id?}  -> {task_id, status, result}

``A2AClient`` is used from a Temporal *activity* (the HTTP call is
nondeterministic IO). ``create_a2a_app`` wraps any handler as an A2A server.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable

import httpx
from pydantic import BaseModel

CARD_PATH = "/.well-known/agent-card.json"
MESSAGE_PATH = "/a2a/message"


class A2AMessageIn(BaseModel):
    """Request body for the A2A task endpoint (module-level so FastAPI resolves it)."""

    message: str
    context_id: str | None = None


@dataclass
class AgentCard:
    name: str
    description: str
    url: str = ""
    version: str = "0.1.0"
    skills: list[str] = field(default_factory=list)


@dataclass
class A2AResult:
    task_id: str
    status: str
    result: str
    agent: str = ""


# handler(message, context) -> reply text  (sync or async)
A2AHandler = Callable[[str, dict], "str | Awaitable[str]"]


class A2AClient:
    """Minimal client for calling a remote A2A agent."""

    def __init__(self, timeout_seconds: float = 30.0, transport: object | None = None) -> None:
        self._timeout = timeout_seconds
        # ``transport`` lets tests target an in-process ASGI app (httpx ASGITransport).
        self._transport = transport

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)  # type: ignore[arg-type]

    async def get_card(self, base_url: str) -> AgentCard:
        async with self._http() as c:
            r = await c.get(base_url.rstrip("/") + CARD_PATH)
            r.raise_for_status()
            data = r.json()
        return AgentCard(**{k: data.get(k) for k in ("name", "description", "url", "version", "skills") if k in data})

    async def send(self, base_url: str, message: str, context_id: str | None = None) -> A2AResult:
        payload = {"message": message, "context_id": context_id or uuid.uuid4().hex}
        async with self._http() as c:
            r = await c.post(base_url.rstrip("/") + MESSAGE_PATH, json=payload)
            r.raise_for_status()
            data = r.json()
        return self._result(data)

    def send_sync(self, base_url: str, message: str, context_id: str | None = None) -> A2AResult:
        """Synchronous A2A call — for use inside a (sync) agent node/activity."""
        payload = {"message": message, "context_id": context_id or uuid.uuid4().hex}
        with httpx.Client(timeout=self._timeout, transport=self._transport) as c:  # type: ignore[arg-type]
            r = c.post(base_url.rstrip("/") + MESSAGE_PATH, json=payload)
            r.raise_for_status()
            data = r.json()
        return self._result(data)

    @staticmethod
    def _result(data: dict) -> A2AResult:
        return A2AResult(
            task_id=str(data.get("task_id", "")),
            status=str(data.get("status", "")),
            result=str(data.get("result", "")),
            agent=str(data.get("agent", "")),
        )


def create_a2a_app(card: AgentCard, handler: A2AHandler):
    """Wrap a handler as an A2A server (FastAPI app). Imported lazily so the
    core library does not depend on FastAPI unless a server is actually run."""
    import inspect

    from fastapi import FastAPI

    app = FastAPI(title=f"A2A: {card.name}")

    @app.get(CARD_PATH)
    async def get_card() -> dict:
        return asdict(card)

    @app.post(MESSAGE_PATH)
    async def message(body: A2AMessageIn) -> dict:
        ctx = {"context_id": body.context_id or uuid.uuid4().hex}
        out = handler(body.message, ctx)
        if inspect.isawaitable(out):
            out = await out
        return {
            "task_id": ctx["context_id"],
            "status": "completed",
            "result": str(out),
            "agent": card.name,
        }

    return app
