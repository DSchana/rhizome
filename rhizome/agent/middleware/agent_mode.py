"""Middleware that swaps the system prompt and filters tools based on the active agent mode.

On every model call, this middleware:

1. Reads the active ``AgentMode`` from the session (via a callable accessor).
2. Idempotently updates the ``SystemMessage`` in graph state (via ``abefore_model``)
   so the conversation history always reflects the current mode's prompt.
3. Filters ``request.tools`` to only those allowed by the mode (via
   ``awrap_model_call``, which is stateless).

State modification uses ``before_model`` / ``abefore_model`` because these hooks
return state updates that go through the ``add_messages`` reducer, persisting the
change in the graph's checkpointed state.  Tool filtering stays in
``wrap_model_call`` / ``awrap_model_call`` because it is a stateless
per-request concern that should not be persisted.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langchain_core.messages import SystemMessage
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelCallResult,
    ModelRequest,
    ModelResponse,
    AgentState
)

from rhizome.logs import get_logger

if TYPE_CHECKING:
    from rhizome.agent.modes import AgentMode

_logger = get_logger("agent.middleware.agent_mode")

# Well-known message ID used for the system prompt so the ``add_messages``
# reducer can replace it in-place when the mode changes.
SYSTEM_PROMPT_MESSAGE_ID = "system-prompt"


def _get_tool_name(tool) -> str | None:
    """Extract the name from a BaseTool instance or a server-side tool dict."""
    if hasattr(tool, "name"):
        return tool.name
    if isinstance(tool, dict):
        return tool.get("name")
    return None


class AgentModeMiddleware(AgentMiddleware):
    """Swap system prompt and filter tools based on the active agent mode.

    System prompt management happens in ``abefore_model`` (state update),
    while tool filtering happens in ``awrap_model_call`` (stateless override).

    Args:
        mode_accessor: A zero-argument callable that returns the current
            ``AgentMode``.  Typically ``lambda: session.active_mode``.
    """

    def __init__(self, mode_accessor: Callable[[], AgentMode]) -> None:
        self._get_mode = mode_accessor

    # -- State update: system message ----------------------------------------

    def before_model(self, state, runtime) -> dict[str, Any] | None:
        return self._update_system_message(state)

    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        return self._update_system_message(state)

    def _update_system_message(self, state: AgentState) -> dict[str, Any] | None:
        """Return a state update that replaces the system message if stale."""
        mode = self._get_mode()
        prompt = mode.system_prompt

        messages = state.get("messages", [])

        # Find the existing system message (by well-known ID or first SystemMessage).
        existing = None
        for msg in messages:
            if isinstance(msg, SystemMessage):
                if msg.id == SYSTEM_PROMPT_MESSAGE_ID:
                    existing = msg
                    break
                # Fall back to the first SystemMessage if it has no ID set.
                if existing is None:
                    existing = msg

        if existing is not None and _system_message_content(existing) == prompt:
            return None  # Already up to date.

        _logger.debug("Updating system message in state for mode %r", mode.name)
        # Use the same ID so add_messages replaces in-place.
        msg_id = existing.id if (existing is not None and existing.id) else SYSTEM_PROMPT_MESSAGE_ID
        return {
            "messages": [SystemMessage(content=prompt, id=msg_id)],
        }

    # -- Stateless override: tool filtering ----------------------------------

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._filter_tools(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return await handler(self._filter_tools(request))

    def _filter_tools(self, request: ModelRequest) -> ModelRequest:
        """Filter request tools to those allowed by the current mode."""
        mode = self._get_mode()

        filtered_tools = [
            t for t in request.tools
            if mode.is_tool_allowed(_get_tool_name(t) or "")
        ]
        if len(filtered_tools) != len(request.tools):
            return request.override(tools=filtered_tools)
        return request


def _system_message_content(msg: SystemMessage) -> str:
    """Extract text content from a SystemMessage regardless of content format."""
    content = msg.content
    if isinstance(content, str):
        return content
    # Content can be a list of blocks (e.g. with cache_control added).
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in content
        )
    return str(content)
