"""Run the ServiceNow third-party agent (A2A) with a local simulator.

    python -m app.entrypoints.servicenow_agent --port 8801                # simulator
    SERVICENOW_MODE=real SERVICENOW_BASE_URL=... SERVICENOW_USER=... \
    SERVICENOW_PASSWORD=... python -m app.entrypoints.servicenow_agent    # real PDI

Exposes an A2A agent (card + /a2a/message) that opens incidents. In simulator
mode the ServiceNow Table API is mounted at /servicenow for inspection.
"""

from __future__ import annotations

import click
import uvicorn

from app.config import load_settings
from app.integrations.servicenow import (
    IncidentStore,
    ServiceNowClient,
    SimulatorBackend,
    create_servicenow_api,
)
from app.platform.a2a import AgentCard, create_a2a_app


def _handler(backend):
    async def handler(message: str, context: dict) -> str:
        short = message.strip().splitlines()[0][:120] if message.strip() else "Agent-opened incident"
        urgency = "2" if any(k in message.lower() for k in ("urgent", "risk", "shortfall")) else "3"
        res = await backend.create_incident(short, message, urgency)
        return f"Opened ServiceNow incident {res.get('number')} ({res.get('short_description')})"

    return handler


@click.command()
@click.option("--port", type=int, default=8801)
@click.option("--host", default="0.0.0.0")
def main(port, host) -> None:
    settings = load_settings()
    sn = settings.third_party.servicenow

    store = None
    if sn.mode == "real" and sn.base_url:
        backend = ServiceNowClient(sn.base_url, sn.username, sn.password, sn.table)
    else:
        store = IncidentStore(seed=True)
        backend = SimulatorBackend(store)

    card = AgentCard(
        name="servicenow",
        description="ServiceNow incident agent",
        url=f"http://{host}:{port}",
        skills=["open_incident"],
    )
    app = create_a2a_app(card, _handler(backend))
    if store is not None:
        app.mount("/servicenow", create_servicenow_api(store))

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
