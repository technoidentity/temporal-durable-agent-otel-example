"""A2A protocol: server card + task endpoint, client round-trip, config, activity."""

from httpx import ASGITransport

from app.config.models import A2AConfig, AppSettings
from app.platform.a2a import AgentCard, A2AClient, create_a2a_app


def _echo(name="peer"):
    def handler(message: str, context: dict) -> str:
        return f"[{name}] {message}"

    return handler


def _app():
    card = AgentCard(name="peer", description="test peer", url="http://peer", skills=["echo"])
    return create_a2a_app(card, _echo())


async def test_client_get_card_in_process():
    client = A2AClient(transport=ASGITransport(app=_app()))
    card = await client.get_card("http://peer")
    assert card.name == "peer"
    assert "echo" in card.skills


async def test_client_send_in_process():
    client = A2AClient(transport=ASGITransport(app=_app()))
    res = await client.send("http://peer", "hello", context_id="ctx-1")
    assert res.status == "completed"
    assert res.result == "[peer] hello"
    assert res.agent == "peer"
    assert res.task_id == "ctx-1"


async def test_async_handler_supported():
    async def ahandler(message: str, context: dict) -> str:
        return f"async:{message}"

    app = create_a2a_app(AgentCard(name="a", description="d"), ahandler)
    client = A2AClient(transport=ASGITransport(app=app))
    res = await client.send("http://a", "x")
    assert res.result == "async:x"


def test_a2a_config_defaults_and_parse():
    assert AppSettings().a2a.enabled is False
    s = AppSettings.model_validate(
        {"a2a": {"enabled": True, "agents": {"servicenow": "http://localhost:8801"}}}
    )
    assert s.a2a.enabled is True
    assert s.a2a.agents["servicenow"] == "http://localhost:8801"


async def test_a2a_activity_calls_client(monkeypatch):
    from app.temporal import a2a_activity as mod
    from app.platform.a2a import A2AResult

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def send(self, url, message, context_id=None):
            return A2AResult(task_id="t", status="completed", result=f"ok:{message}", agent="x")

    monkeypatch.setattr(mod, "A2AClient", FakeClient)
    out = await mod.a2a_call_activity(mod.A2ACallInput(target_url="http://x", message="hi"))
    assert out == "ok:hi"
