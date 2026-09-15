"""Agent graph state.

The hello-agent uses LangGraph's built-in ``MessagesState`` (a single
``messages`` channel with add-messages reducer). It is aliased here so the rest
of the code depends on our name, not the library path, and so a richer state can
be introduced later without touching call sites.
"""

from __future__ import annotations

from langgraph.graph import MessagesState

AgentState = MessagesState

__all__ = ["AgentState"]
