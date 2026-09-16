"""ServiceNow simulator, backend, risk detection, A2A agent handler, config."""

from httpx import ASGITransport

from app.config.models import AppSettings
from app.integrations.servicenow import (
    IncidentStore,
    SimulatorBackend,
    create_servicenow_api,
    detect_risk,
)
from app.platform.a2a import A2AClient, AgentCard, create_a2a_app


def test_store_seeded_and_numbers():
    store = IncidentStore(seed=True)
    seeded = store.all()
    assert len(seeded) == 2
    inc = store.create("New risk", "desc", urgency="2")
    assert inc.number.startswith("INC")
    assert len(store.all()) == 3
    # numbers are unique and incrementing
    numbers = [i.number for i in store.all()]
    assert len(set(numbers)) == len(numbers)


def test_table_api_create_and_list():
    from fastapi.testclient import TestClient

    store = IncidentStore(seed=False)
    client = TestClient(create_servicenow_api(store))
    r = client.post("/api/now/table/incident", json={"short_description": "Delay", "urgency": "2"})
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["number"].startswith("INC")
    assert result["short_description"] == "Delay"
    listed = client.get("/api/now/table/incident").json()["result"]
    assert len(listed) == 1


def test_detect_risk():
    kws = ["risk", "delay", "shortfall"]
    assert detect_risk("There is a delivery DELAY expected", kws) is True
    assert detect_risk("all good, shipping normally", kws) is False


async def test_servicenow_a2a_agent_opens_incident():
    store = IncidentStore(seed=False)
    backend = SimulatorBackend(store)

    async def handler(message: str, context: dict) -> str:
        res = await backend.create_incident(message[:80], message, "2")
        return f"Opened ServiceNow incident {res['number']}"

    app = create_a2a_app(AgentCard(name="servicenow", description="d"), handler)
    client = A2AClient(transport=ASGITransport(app=app))
    res = await client.send("http://sn", "Fulfillment risk: stock shortfall")
    assert "INC" in res.result
    assert len(store.all()) == 1


def test_servicenow_config_defaults():
    sn = AppSettings().third_party.servicenow
    assert sn.enabled is False
    assert sn.mode == "simulator"
    assert sn.open_incident_on_risk is True
    assert "risk" in sn.risk_keywords
