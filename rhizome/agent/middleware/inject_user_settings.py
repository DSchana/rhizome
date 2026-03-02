"""Middleware that injects user settings into the last human message.

Prepends a ``<UserSettings>`` XML block to the last human message and wraps the
original content in ``<UserMessage>``.  This lets the model see per-request
settings (e.g. verbosity) without modifying the system prompt or invalidating
any prompt cache.

Subclasses can override :meth:`get_settings` to extract settings from the
runtime context, or pass ``settings_attribute`` for simple attribute access.

Usage::

    middleware = InjectUserSettingsMiddleware[MyContext](
        settings_attribute="user_preferences",
    )
"""

from __future__ import annotations

import json
from typing import Any, Callable, Generic, TypeVar

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain.messages import HumanMessage

from rhizome.logs import get_logger

ContextT = TypeVar("ContextT")


class InjectUserSettingsMiddleware(AgentMiddleware, Generic[ContextT]):
    """Wraps model calls to inject user settings into the latest human message.

    Settings are serialised as a ``<UserSettings>`` XML block prepended to the
    last human message's content.  The original message is wrapped in a
    ``<UserMessage>`` block.

    Args:
        include_system_prompt: If ``True``, :meth:`system_prompt` output will
            be included in the agent's system prompt. Defaults to ``False``.
        settings_attribute: Name of an attribute on the runtime context to
            read settings from. If provided, :meth:`get_settings` does not
            need to be overridden.
    """

    def __init__(
        self,
        *,
        include_system_prompt: bool = False,
        settings_attribute: str | None = None,
    ) -> None:
        self._include_system_prompt = include_system_prompt
        self._settings_attribute = settings_attribute
        self._logger = get_logger("agent.middleware.inject_user_settings")

    # -- Public API -----------------------------------------------------------

    def get_settings(self, context: ContextT) -> dict[str, Any]:
        """Extract settings from the runtime context.

        Subclasses must override this to return the settings dict for the
        current request.
        """
        if self._settings_attribute:
            return getattr(context, self._settings_attribute, {}) or {}
        raise NotImplementedError(
            "Subclasses must implement get_settings() to extract settings "
            "from the runtime context."
        )

    def wrap_message(
        self, msg: HumanMessage, context: ContextT
    ) -> HumanMessage:
        """Prepend the settings block and wrap original content.

        Override in subclasses to customise how settings are presented.
        """
        settings = self.get_settings(context)
        if not settings:
            return msg
        wrapped = (
            f"{self._format_settings_block(settings)}\n"
            f"<UserMessage>\n{msg.content}\n</UserMessage>"
        )
        return HumanMessage(content=wrapped, id=msg.id)

    @classmethod
    def system_prompt(cls) -> str:
        """Return a system prompt fragment explaining the settings injection."""
        return (
            "\n"
            "# User Settings Injection\n"
            f"NOTE: this section has been automatically added to the system prompt by {cls.__name__}.\n"
            "The latest user message may be accompanied by a <UserSettings> block containing JSON-formatted preferences. "
            "These settings reflect the user's current configuration and should inform your responses accordingly. "
            "The actual user message will be wrapped in a <UserMessage> block. "
            "If no <UserSettings> block is present, you can safely ignore this part of the system prompt.\n"
        )

    # -- Middleware hook -------------------------------------------------------

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        messages = self._prepare_messages(request)
        return handler(request.override(messages=messages))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        messages = self._prepare_messages(request)
        return await handler(request.override(messages=messages))

    # -- Internals ------------------------------------------------------------

    def _prepare_messages(self, request: ModelRequest) -> list:
        """Build the modified message list for a request."""
        messages = list(request.messages)

        last = messages[-1]
        if isinstance(last, HumanMessage):
            context = request.runtime.context
            messages[-1] = self.wrap_message(last, context)

        return messages

    def _format_settings_block(self, settings: dict[str, Any]) -> str:
        """Serialise settings as an XML-wrapped JSON block."""
        payload = json.dumps(settings, indent=2)
        return f"<UserSettings>\n```json\n{payload}\n```\n</UserSettings>"
