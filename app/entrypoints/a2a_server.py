"""Run a standalone A2A agent server.

    python -m app.entrypoints.a2a_server --name peer --port 8802 --handler echo
    python -m app.entrypoints.a2a_server --name peer --port 8802 \
        --handler lyzr --lyzr-agent-id <id>

The same server shape is reused for third-party agents (e.g. ServiceNow) by
swapping the handler. ``echo`` needs no credentials; ``lyzr`` uses LYZR_API_KEY.
"""

from __future__ import annotations

import os

import click
import uvicorn

from app.platform.a2a import AgentCard, create_a2a_app


def _echo_handler(name: str):
    def handler(message: str, context: dict) -> str:
        return f"[{name}] received: {message}"

    return handler


def _lyzr_handler(agent_id: str):
    from app.agent.lyzr import LyzrChatModel

    key = os.environ.get("LYZR_API_KEY", "")
    if not key:
        raise SystemExit("lyzr handler requires LYZR_API_KEY")
    base_url = os.environ.get("LYZR_BASE_URL", "")
    kwargs = {"api_key": key, "agent_id": agent_id}
    if base_url:
        kwargs["base_url"] = base_url
    llm = LyzrChatModel(**kwargs)

    def handler(message: str, context: dict) -> str:
        return str(llm.invoke(message).content)

    return handler


@click.command()
@click.option("--name", required=True, help="Agent name (shown on the card).")
@click.option("--description", default="A2A agent", help="Agent description.")
@click.option("--port", type=int, default=8802)
@click.option("--host", default="0.0.0.0")
@click.option("--handler", type=click.Choice(["echo", "lyzr"]), default="echo")
@click.option("--lyzr-agent-id", "lyzr_agent_id", default="", help="Lyzr agent id (handler=lyzr).")
@click.option("--skill", "skills", multiple=True, help="Advertised skill (repeatable).")
def main(name, description, port, host, handler, lyzr_agent_id, skills) -> None:
    if handler == "lyzr":
        if not lyzr_agent_id:
            raise SystemExit("--lyzr-agent-id is required for handler=lyzr")
        fn = _lyzr_handler(lyzr_agent_id)
    else:
        fn = _echo_handler(name)

    card = AgentCard(
        name=name,
        description=description,
        url=f"http://{host}:{port}",
        skills=list(skills),
    )
    app = create_a2a_app(card, fn)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
