"""Demo UI control-plane endpoints (Temporal client faked, no server needed)."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config.models import AppSettings, HITLConfig, MultiAgentConfig, ServiceNowConfig, ThirdPartyConfig
from app.ui.server import create_ui_app


class FakeHandle:
    def __init__(self, wfid, state):
        self.id = wfid
        self._state = state

    async def describe(self):
        return SimpleNamespace(status=SimpleNamespace(name=self._state["status"]))

    async def query(self, _q):
        return self._state.get("pending", {"pending": False})

    async def signal(self, _s, args=None):
        self._state["signalled"] = args

    async def result(self):
        return self._state.get("result")


class FakeClient:
    def __init__(self):
        self.started = []
        self.states = {}

    async def start_workflow(self, fn, inp, id, task_queue, execution_timeout):
        self.started.append({"id": id, "input": inp})
        self.states[id] = {"status": "RUNNING", "pending": {"pending": True, "details": "approve me"}}
        return FakeHandle(id, self.states[id])

    def get_workflow_handle(self, wfid):
        return FakeHandle(wfid, self.states.setdefault(wfid, {"status": "RUNNING"}))


def _settings():
    return AppSettings(
        multi_agent=MultiAgentConfig(enabled=True),
        hitl=HITLConfig(enabled=True, discount_threshold=15.0),
        third_party=ThirdPartyConfig(servicenow=ServiceNowConfig(enabled=True)),
    )


def _client_and_fake():
    fake = FakeClient()

    async def factory():
        return fake

    app = create_ui_app(_settings(), client_factory=factory)
    return TestClient(app), fake


def test_meta():
    client, _ = _client_and_fake()
    m = client.get("/api/meta").json()
    assert "intake" in m["agents"] and "supervisor" in m["agents"]
    assert m["servicenow_enabled"] is True
    assert m["hitl"]["threshold"] == 15.0
    assert set(m["links"]) == {"temporal_ui", "grafana", "prometheus", "phoenix"}


def test_start_order_passes_overrides():
    client, fake = _client_and_fake()
    body = {
        "request": "500 cases at 20% discount",
        "threshold": 5,
        "hitl_mode": "inline",
        "chaos": {"target": "inventory", "mode": "transient_error", "attempts": 1},
    }
    res = client.post("/api/orders", json=body).json()
    assert res["workflow_id"].startswith("pepsico-order-")
    started = fake.started[0]["input"]
    assert started.discount_threshold == 5
    assert started.chaos["target"] == "inventory"
    assert started.servicenow_a2a_url  # servicenow enabled -> url passed


def test_order_status_and_decision():
    client, fake = _client_and_fake()
    wfid = client.post("/api/orders", json={"request": "x at 20% discount"}).json()["workflow_id"]

    s = client.get(f"/api/orders/{wfid}").json()
    assert s["status"] == "RUNNING"
    assert s["pending"]["pending"] is True

    r = client.post(f"/api/orders/{wfid}/decision", json={"approved": True, "note": "ok"})
    assert r.json()["ok"] is True
    assert fake.states[wfid]["signalled"] == [True, "ui", "ok"]


def test_list_orders_tracks_runs():
    client, _ = _client_and_fake()
    client.post("/api/orders", json={"request": "a at 20% discount"})
    client.post("/api/orders", json={"request": "b at 20% discount"})
    runs = client.get("/api/orders").json()["runs"]
    assert len(runs) == 2
