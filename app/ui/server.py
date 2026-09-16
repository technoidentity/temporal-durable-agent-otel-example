"""FastAPI control plane for the demo UI.

Everything the demo needs is driven from here: start order workflows with any
mix of HITL + chaos, inspect status, approve/reject pending gates, and link out
to Temporal UI / Grafana / Prometheus / Phoenix. The Temporal client is created
lazily (and can be injected for tests).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent.multi import KNOWN_ROLES
from app.config.models import AppSettings
from app.temporal.client import create_temporal_client
from app.workflows.order_workflow import OrderWorkflow, OrderWorkflowInput

_STATIC = Path(__file__).parent / "static"


class ChaosIn(BaseModel):
    target: str = ""
    mode: str = "none"
    attempts: int = 1
    latency_seconds: float = 0.0
    force_hitl: bool = False


class OrderIn(BaseModel):
    request: str
    threshold: float | None = None
    hitl_mode: str | None = None
    no_hitl: bool = False
    chaos: ChaosIn | None = None


class DecisionIn(BaseModel):
    approved: bool
    approver: str = "ui"
    note: str = ""


def create_ui_app(
    settings: AppSettings,
    client_factory: Callable[[], Awaitable[Any]] | None = None,
) -> FastAPI:
    app = FastAPI(title="PepsiCo Agent Ops")
    app.state.settings = settings
    app.state.client = None
    app.state.client_factory = client_factory or (lambda: create_temporal_client(settings))
    app.state.runs: list[dict] = []

    async def client() -> Any:
        if app.state.client is None:
            app.state.client = await app.state.client_factory()
        return app.state.client

    if _STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/api/meta")
    async def meta() -> dict:
        sn = settings.third_party.servicenow
        obs = settings.observability
        return {
            "app": settings.app.name,
            "environment": settings.app.environment.value,
            "provider": settings.llm.provider.value,
            "graph_name": settings.multi_agent.graph_name,
            "agents": list(KNOWN_ROLES),
            "hitl": {
                "enabled": settings.hitl.enabled,
                "threshold": settings.hitl.discount_threshold,
                "mode": settings.hitl.mode.value,
            },
            "chaos_modes": ["transient_error", "permanent_error", "latency"],
            "servicenow_enabled": sn.enabled,
            "links": {
                "temporal_ui": settings.infrastructure.temporal_ui_url,
                "grafana": settings.infrastructure.grafana_url,
                "prometheus": settings.infrastructure.prometheus_url,
                "phoenix": obs.phoenix.endpoint,
            },
        }

    @app.post("/api/orders")
    async def start_order(body: OrderIn) -> dict:
        c = await client()
        wfid = f"{settings.multi_agent.graph_name}-{uuid.uuid4().hex[:12]}"
        sn = settings.third_party.servicenow
        chaos = body.chaos.model_dump() if body.chaos else {}
        inp = OrderWorkflowInput(
            request=body.request,
            graph_name=settings.multi_agent.graph_name,
            hitl_enabled=(not body.no_hitl) and settings.hitl.enabled,
            hitl_mode=body.hitl_mode or settings.hitl.mode.value,
            discount_threshold=(
                body.threshold if body.threshold is not None else settings.hitl.discount_threshold
            ),
            approval_timeout_seconds=settings.hitl.approval_timeout_seconds,
            on_timeout=settings.hitl.on_timeout.value,
            servicenow_a2a_url=sn.a2a_url if sn.enabled else "",
            open_incident_on_risk=sn.enabled and sn.open_incident_on_risk,
            risk_keywords=list(sn.risk_keywords),
            chaos=chaos,
        )
        await c.start_workflow(
            OrderWorkflow.run,
            inp,
            id=wfid,
            task_queue=settings.temporal.task_queue,
            execution_timeout=timedelta(
                seconds=settings.temporal.workflow.execution_timeout_seconds
            ),
        )
        app.state.runs.insert(0, {"id": wfid, "request": body.request})
        app.state.runs = app.state.runs[:25]
        return {"workflow_id": wfid}

    @app.get("/api/orders")
    async def list_orders() -> dict:
        return {"runs": app.state.runs}

    @app.get("/api/orders/{wfid}")
    async def order_status(wfid: str) -> dict:
        c = await client()
        handle = c.get_workflow_handle(wfid)
        desc = await handle.describe()
        status = desc.status.name if getattr(desc, "status", None) else "UNKNOWN"
        pending: dict = {"pending": False}
        result = None
        if status == "RUNNING":
            try:
                pending = await handle.query(OrderWorkflow.pending)
            except Exception:
                pending = {"pending": False}
        elif status == "COMPLETED":
            try:
                result = await handle.result()
            except Exception:
                result = None
        return {"id": wfid, "status": status, "pending": pending, "result": result}

    @app.post("/api/orders/{wfid}/decision")
    async def decide(wfid: str, body: DecisionIn) -> dict:
        c = await client()
        handle = c.get_workflow_handle(wfid)
        await handle.signal(OrderWorkflow.decide, args=[body.approved, body.approver, body.note])
        return {"ok": True}

    return app
