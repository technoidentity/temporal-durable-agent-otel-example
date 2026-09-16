"""Multi-agent order pipeline: config, graph shape, and an offline run."""

from app.agent.multi import KNOWN_ROLES, build_order_graph
from app.config.models import AppSettings, LLMConfig, LLMProvider, MultiAgentConfig


def _settings(pipeline=None) -> AppSettings:
    return AppSettings(
        llm=LLMConfig(provider=LLMProvider.fake),
        multi_agent=MultiAgentConfig(
            enabled=True, pipeline=pipeline or list(KNOWN_ROLES)
        ),
    )


def test_multi_agent_config_defaults():
    s = AppSettings()
    assert s.multi_agent.enabled is False
    assert s.multi_agent.graph_name == "pepsico-order"
    assert "intake" in s.multi_agent.pipeline and "supervisor" in s.multi_agent.pipeline


def test_build_order_graph_nodes_and_edges():
    graph = build_order_graph(_settings())
    for role in KNOWN_ROLES:
        assert graph.nodes[role].metadata["execute_in"] == "activity"
        assert "start_to_close_timeout" in graph.nodes[role].metadata


def test_pipeline_subset_and_order():
    graph = build_order_graph(_settings(pipeline=["intake", "pricing"]))
    assert set(graph.nodes) >= {"intake", "pricing"}
    assert "inventory" not in graph.nodes


async def test_order_pipeline_runs_offline():
    graph = build_order_graph(_settings()).compile()
    result = await graph.ainvoke({"request": "500 cases Pepsi 330ml, 20% discount"})
    for stage in ("intake", "inventory", "pricing", "fulfillment", "account", "outcome"):
        assert result.get(stage), f"missing stage output: {stage}"
    # The fake model echoes its prompt, so distinct nodes yield distinct text.
    assert result["intake"] != result["outcome"]
