"""ServiceNow integration: a local simulator plus a real-instance client.

The simulator mimics the ServiceNow Table API for incidents (seeded), so the
rest of the system talks to "ServiceNow" the same way whether it is the local
simulator or a real PDI. Switching is a config change (mode + base_url + creds).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol

import httpx
from pydantic import BaseModel


class IncidentIn(BaseModel):
    """Request body for creating an incident (module-level for FastAPI)."""

    short_description: str
    description: str = ""
    urgency: str = "3"


def _sys_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Incident:
    number: str
    short_description: str
    sys_id: str = field(default_factory=_sys_id)
    description: str = ""
    urgency: str = "3"
    state: str = "1"  # 1 = New
    opened_at: str = ""
    # Idempotency key (ServiceNow's own field). A repeated create with the same
    # correlation_id upserts instead of opening a duplicate ticket (review B3).
    correlation_id: str = ""


_SEED = [
    ("Delivery delay for Star Distributors", "Truck breakdown en route; ETA slipped 1 day."),
    ("Out of stock: Mountain Dew 500ml (DC-East)", "Replenishment order pending from plant."),
]


class IncidentStore:
    """In-memory incident table with sequential ServiceNow-style numbers."""

    def __init__(self, seed: bool = True) -> None:
        self._items: list[Incident] = []
        self._counter = 10_000
        if seed:
            for sd, desc in _SEED:
                self.create(sd, desc, urgency="2")

    def _next_number(self) -> str:
        self._counter += 1
        return f"INC{self._counter:07d}"

    def create(
        self,
        short_description: str,
        description: str = "",
        urgency: str = "3",
        correlation_id: str = "",
    ) -> Incident:
        # Upsert on correlation_id: a retried create returns the existing ticket.
        if correlation_id:
            for existing in self._items:
                if existing.correlation_id == correlation_id:
                    return existing
        inc = Incident(
            number=self._next_number(),
            short_description=short_description[:160],
            description=description,
            urgency=urgency,
            opened_at=datetime.now(timezone.utc).isoformat(),
            correlation_id=correlation_id,
        )
        self._items.append(inc)
        return inc

    def all(self) -> list[Incident]:
        return list(self._items)


def incident_result(inc: Incident) -> dict:
    """ServiceNow Table API 'result' shape for a single incident."""
    return asdict(inc)


# --------------------------------------------------------------------------- #
# backends: how the agent actually creates an incident
# --------------------------------------------------------------------------- #
class ServiceNowBackend(Protocol):
    async def create_incident(
        self, short_description: str, description: str, urgency: str, correlation_id: str = ""
    ) -> dict:
        ...


class SimulatorBackend:
    """Backed by an in-process IncidentStore."""

    def __init__(self, store: IncidentStore) -> None:
        self._store = store

    async def create_incident(
        self, short_description: str, description: str, urgency: str = "3", correlation_id: str = ""
    ) -> dict:
        return incident_result(
            self._store.create(short_description, description, urgency, correlation_id)
        )


class ServiceNowClient:
    """Client for a real ServiceNow instance (Table API, basic auth)."""

    def __init__(self, base_url: str, username: str, password: str, table: str = "incident") -> None:
        self._base = base_url.rstrip("/")
        self._auth = (username, password)
        self._table = table

    async def create_incident(
        self, short_description: str, description: str, urgency: str = "3", correlation_id: str = ""
    ) -> dict:
        url = f"{self._base}/api/now/table/{self._table}"
        payload = {
            "short_description": short_description,
            "description": description,
            "urgency": urgency,
        }
        if correlation_id:
            payload["correlation_id"] = correlation_id  # ServiceNow dedup field
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(url, json=payload, auth=self._auth,
                             headers={"Accept": "application/json"})
            r.raise_for_status()
            return r.json().get("result", {})

    async def list_incidents(self, limit: int = 20) -> list[dict]:
        url = f"{self._base}/api/now/table/{self._table}?sysparm_limit={limit}"
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(url, auth=self._auth, headers={"Accept": "application/json"})
            r.raise_for_status()
            return r.json().get("result", [])


# --------------------------------------------------------------------------- #
# risk detection (deterministic; safe for workflow code)
# --------------------------------------------------------------------------- #
def detect_risk(text: str, keywords: list[str]) -> bool:
    low = (text or "").lower()
    return any(k.lower() in low for k in keywords)


# --------------------------------------------------------------------------- #
# simulator Table API app
# --------------------------------------------------------------------------- #
def create_servicenow_api(store: IncidentStore):
    """FastAPI app exposing the ServiceNow Table API subset for incidents."""
    from fastapi import FastAPI

    app = FastAPI(title="ServiceNow Simulator")

    @app.post("/api/now/table/incident")
    async def create(body: IncidentIn) -> dict:
        return {"result": incident_result(store.create(body.short_description, body.description, body.urgency))}

    @app.get("/api/now/table/incident")
    async def list_incidents() -> dict:
        return {"result": [incident_result(i) for i in store.all()]}

    return app
