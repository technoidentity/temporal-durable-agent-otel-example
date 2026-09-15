"""LangGraph construction, the fake model, and the current_time tool."""

import re

from app.agent.graph import build_graph
from app.agent.nodes import FakeToolCallingModel, build_llm
from app.agent.tools import current_time
from app.config.models import AppSettings, LLMConfig, LLMProvider

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*\+00:00$")


def _fake_settings() -> AppSettings:
    return AppSettings(llm=LLMConfig(provider=LLMProvider.fake))


def test_current_time_returns_iso_utc():
    value = current_time.invoke({})
    assert ISO_RE.match(value), value


def test_build_llm_fake():
    llm = build_llm(LLMConfig(provider=LLMProvider.fake))
    assert isinstance(llm, FakeToolCallingModel)


def test_build_llm_openai_requires_key():
    import pytest

    with pytest.raises(ValueError):
        build_llm(LLMConfig(provider=LLMProvider.openai, api_key=""))


async def test_graph_end_to_end_with_fake_model():
    graph = build_graph(_fake_settings()).compile()
    out = await graph.ainvoke({"messages": [{"role": "user", "content": "What time is it?"}]})
    messages = out["messages"]
    # human -> ai(tool_call) -> tool -> ai(final)
    assert len(messages) == 4
    assert messages[1].tool_calls[0]["name"] == "current_time"
    assert "current UTC time is" in messages[-1].content


def test_graph_nodes_tagged_for_activity():
    graph = build_graph(_fake_settings())
    for name in ("agent", "tools"):
        assert graph.nodes[name].metadata["execute_in"] == "activity"
        assert "start_to_close_timeout" in graph.nodes[name].metadata
