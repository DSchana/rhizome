"""Middleware that disables parallel tool calls.

LangGraph's ``ToolNode`` dispatches multiple tool calls via
``asyncio.gather``, but the agent shares a single ``AsyncSession``
across all tools.  SQLAlchemy's async session is **not** safe for
concurrent use, so parallel tool execution causes
``InvalidRequestError`` and double-flush races.

This middleware injects ``parallel_tool_calls=False`` into
``model_settings`` so that ``bind_tools`` tells the provider to emit
only one tool call per response.
"""

from __future__ import annotations

from typing import Any, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)


class DisableParallelToolCallsMiddleware(AgentMiddleware):
    """Set ``parallel_tool_calls=False`` on every model request."""

    def _patched(self, request: ModelRequest) -> ModelRequest:
        settings = {**request.model_settings, "parallel_tool_calls": False}
        return request.override(model_settings=settings)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._patched(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return await handler(self._patched(request))
