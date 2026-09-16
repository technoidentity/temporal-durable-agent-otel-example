"""LLM provider selection: Lyzr (mocked HTTP) and Ollama (OpenAI-compatible)."""

import pytest

from app.agent import lyzr as lyzr_mod
from app.agent.lyzr import LyzrChatModel
from app.agent.nodes import build_llm
from app.config.models import LLMConfig, LLMProvider


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_build_llm_lyzr_requires_agent_id():
    with pytest.raises(ValueError):
        build_llm(LLMConfig(provider=LLMProvider.lyzr, api_key="k", lyzr_agent_id=""))


def test_build_llm_lyzr_ok():
    llm = build_llm(
        LLMConfig(provider=LLMProvider.lyzr, api_key="k", lyzr_agent_id="agent-1")
    )
    assert isinstance(llm, LyzrChatModel)
    assert llm.agent_id == "agent-1"


def test_lyzr_payload_uses_latest_message_and_system():
    from langchain_core.messages import HumanMessage, SystemMessage

    m = LyzrChatModel(api_key="k", agent_id="a", user_id="u")
    payload = m._payload([SystemMessage(content="be terse"), HumanMessage(content="hi there")])
    assert payload["agent_id"] == "a"
    assert payload["user_id"] == "u"
    assert payload["message"] == "hi there"
    assert payload["system_prompt_variables"]["system"] == "be terse"
    assert payload["session_id"]


def test_lyzr_invoke_parses_response(monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResp({"response": "the answer"})

    monkeypatch.setattr(lyzr_mod.httpx, "post", fake_post)
    m = LyzrChatModel(api_key="secret", agent_id="a")
    out = m.invoke("what is up")
    assert out.content == "the answer"
    assert captured["url"].endswith("/v3/inference/chat/")
    assert captured["headers"]["x-api-key"] == "secret"


def test_build_llm_ollama_returns_openai_client():
    llm = build_llm(LLMConfig(provider=LLMProvider.ollama, model="llama3.1"))
    # Uses ChatOpenAI under the hood pointed at Ollama's OpenAI-compatible API.
    assert llm.__class__.__name__ == "ChatOpenAI"
    assert str(llm.openai_api_base).rstrip("/").endswith("/v1")
