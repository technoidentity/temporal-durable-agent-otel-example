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
from typing import Any, Awaitable, Callable, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.agent.multi import KNOWN_ROLES
from app.config.models import AppSettings
from app.temporal.client import create_temporal_client
from app.workflows.order_workflow import OrderWorkflow, OrderWorkflowInput
from app.workflows.approval_workflow import ApprovalWorkflow
from app.ui.execution import execution_view

_STATIC = Path(__file__).parent / "static"


class ChaosIn(BaseModel):
    target: str = ""
    mode: Literal["none", "transient_error", "permanent_error", "latency"] = "none"
    attempts: int = Field(default=1, ge=0)
    latency_seconds: float = Field(default=0.0, ge=0, le=3600)
    force_hitl: bool = False


class OrderIn(BaseModel):
    request: str = Field(min_length=1, max_length=10000)
    threshold: float | None = Field(default=None, ge=0, le=100)
    hitl_mode: Literal["inline", "child"] | None = None
    no_hitl: bool = False
    chaos: ChaosIn | None = None

    @field_validator("request")
    @classmethod
    def nonblank_request(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a distributor request.")
        return value.strip()


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
            "pipeline": [r for r in settings.multi_agent.pipeline if r in KNOWN_ROLES],
            "namespace": settings.temporal.namespace,
            "multi_agent_enabled": settings.multi_agent.enabled,
            "hitl": {
                "enabled": settings.hitl.enabled,
                "threshold": settings.hitl.discount_threshold,
                "mode": settings.hitl.mode.value,
            },
            "chaos_modes": ["transient_error", "permanent_error", "latency"],
            "servicenow_enabled": sn.enabled,
            "servicenow_mode": sn.mode,
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
        execution = await execution_view(
            handle, desc, [r for r in settings.multi_agent.pipeline if r in KNOWN_ROLES],
            getattr(c, "data_converter", None),
        )
        if status == "RUNNING":
            try:
                child_id = execution.get("child_workflow_id")
                approval_handle = c.get_workflow_handle(child_id) if child_id else handle
                pending = await approval_handle.query(ApprovalWorkflow.pending if child_id else OrderWorkflow.pending)
            except Exception:
                pending = {"pending": False, "unavailable": True}
        elif status == "COMPLETED":
            try:
                result = await handle.result()
            except Exception:
                result = None
        return {"id": wfid, "status": status, "pending": pending, "result": result, **execution}

    @app.post("/api/orders/{wfid}/decision")
    async def decide(wfid: str, body: DecisionIn) -> dict:
        c = await client()
        handle = c.get_workflow_handle(wfid)
        desc = await handle.describe()
        if desc.status.name != "RUNNING":
            raise HTTPException(409, "This workflow has already closed. Refresh its status.")
        execution = await execution_view(handle, desc, [], getattr(c, "data_converter", None))
        child_id = execution.get("child_workflow_id")
        target = c.get_workflow_handle(child_id) if child_id else handle
        pending = await target.query(ApprovalWorkflow.pending if child_id else OrderWorkflow.pending)
        if not pending.get("pending"):
            raise HTTPException(409, "This workflow is not waiting for approval. Refresh its status.")
        await target.signal(ApprovalWorkflow.decide if child_id else OrderWorkflow.decide,
                            args=[body.approved, body.approver, body.note])
        return {"ok": True}

    return app
