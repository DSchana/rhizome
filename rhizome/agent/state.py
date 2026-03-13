"""Custom graph state schema for the root agent."""

from __future__ import annotations

from langchain.agents.middleware.types import AgentState

from typing import Annotated


class RhizomeAgentState(AgentState):
    """Extended agent state with mode tracking for checkpoint/replay.

    The ``mode`` field records the active session mode (``"idle"``,
    ``"learn"``, ``"review"``).  It uses default last-write-wins
    semantics (no reducer annotation needed).

    Two paths update this field:

    - **User-initiated** (shift+tab, slash commands): bridged into graph
      state via ``AgentModeMiddleware.set_pending_user_mode`` →
      ``abefore_model`` state update.
    - **Agent-initiated** (``set_mode`` tool): the tool returns a
      ``Command(update={"mode": ...})`` directly.
    """

    mode: Annotated[str, lambda x, y: y]
    # Remark: in parallel executions of the set_mode tool, the last one wins.
