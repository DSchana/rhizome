"""Middleware that injects user settings into agent messages without
invalidating Anthropic's prompt cache.

The core problem: Anthropic's prompt caching works on a prefix basis. If you
modify the system prompt (e.g. via ``@dynamic_prompt``) or inject content into
earlier messages, the entire cache is invalidated. This middleware sidesteps
that by:

1. Only modifying the **last** human message (appending user settings).
2. Placing a ``cache_control`` breakpoint on the **penultimate** message so
   the API knows everything before it is a stable, cacheable prefix.

Subclasses can override :meth:`get_settings` to extract settings from the
runtime context, and optionally :meth:`wrap_message` to customise how settings
are presented to the model. Alternatively, pass ``settings_attribute`` to pull
settings directly from a named attribute on the context object.

Usage::

    # Option 1: settings_attribute for simple attribute access
    middleware = AnthropicCacheAwareSettingsMiddleware[MyContext](
        settings_attribute="user_preferences",
    )

    # Option 2: subclass for custom logic
    class MySettingsMiddleware(
        AnthropicCacheAwareSettingsMiddleware[MyContext]
    ):
        def get_settings(self, context: MyContext) -> dict[str, Any]:
            return context.user_preferences

    middleware = MySettingsMiddleware()
"""

from __future__ import annotations

import json
from typing import Any, Callable, Generic, Literal, TypeVar

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain.messages import HumanMessage

from rhizome.logs import get_logger

ContextT = TypeVar("ContextT")


class AnthropicCacheAwareSettingsMiddleware(AgentMiddleware, Generic[ContextT]):
    """Wraps model calls to inject user settings into the latest human message.

    Settings are serialised as a ``<UserSettings>`` XML block prepended to the
    last human message's content.  A ``cache_control`` breakpoint is placed on
    the penultimate message so that Anthropic's API treats everything before it
    as a cacheable prefix.

    Subclasses can implement :meth:`get_settings` to extract settings from the
    runtime context, or pass ``settings_attribute`` for simple attribute access.

    Args:
        ttl: Optional TTL for the cache control block. If provided, this sets 
            the cache control type to "ephemeral" with the given TTL. Ignored if
            ``cache_control`` is provided.
        cache_control: Anthropic cache-control descriptor applied to the
            penultimate message. Defaults to 5-minute ephemeral caching.
        include_system_prompt: If ``True``, :meth:`system_prompt` output will
            be included in the agent's system prompt. Defaults to ``False``.
        settings_attribute: Name of an attribute on the runtime context to
            read settings from. If provided, :meth:`get_settings` does not
            need to be overridden.
    """

    # Anthropic's default cache control block. "ephemeral" with a TTL means the
    # cache entry lives for that duration after last use.
    DEFAULT_CACHE_CONTROL: dict[str, str] = {"type": "ephemeral", "ttl": "5m"}

    def __init__(
        self,
        *,
        ttl: Literal["5m", "1h"] | None = None,
        cache_control: dict[str, str] | None = None,
        include_system_prompt: bool = False,
        settings_attribute: str | None = None,
    ) -> None:
        if ttl is not None:
            cache_control = {"type": "ephemeral", "ttl": ttl}
        self._cache_control = cache_control or self.DEFAULT_CACHE_CONTROL
        self._include_system_prompt = include_system_prompt
        self._settings_attribute = settings_attribute
        self._logger = get_logger("agent.middleware.cache_aware_settings")

    # -- Public API -----------------------------------------------------------

    def get_settings(self, context: ContextT) -> dict[str, Any]:
        """Extract settings from the runtime context.

        Subclasses must override this to return the settings dict for the
        current request.

        Args:
            context: The runtime context for the current model call.
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

        Args:
            msg: The original human message.
            context: The runtime context for the current model call.
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
        """Return a system prompt fragment explaining the settings injection.

        This is a classmethod so it can be used without an instance — e.g.
        when constructing a system prompt manually.
        """
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
        """Intercept the model request to inject settings ephemerally.

        This modifies a copy of the request's messages — the graph state is
        never touched.
        """
        messages = self._prepare_messages(request)
        return handler(request.override(messages=messages))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        """Async variant of :meth:`wrap_model_call`."""
        messages = self._prepare_messages(request)
        return await handler(request.override(messages=messages))

    # -- Internals ------------------------------------------------------------

    def _prepare_messages(self, request: ModelRequest) -> list:
        """Build the modified message list for a request."""
        messages = list(request.messages)

        # Place a cache breakpoint on the penultimate message so the stable
        # prefix remains cached across turns.
        if len(messages) >= 2:
            self._logger.debug("Injecting cache control breakpoint (messages=%d)", len(messages))
            try:
                messages[-2] = self._with_cache_control(messages[-2])
            except Exception as e:
                import traceback
                self._logger.error("Failed to add cache control: %s", traceback.format_exc())

        # Wrap the last human message with settings.
        last = messages[-1]
        if isinstance(last, HumanMessage):
            context = request.runtime.context
            messages[-1] = self.wrap_message(last, context)

        return messages

    def _format_settings_block(self, settings: dict[str, Any]) -> str:
        """Serialise settings as an XML-wrapped JSON block."""
        payload = json.dumps(settings, indent=2)
        return f"<UserSettings>\n```json\n{payload}\n```\n</UserSettings>"

    def _with_cache_control(self, msg):
        """Return a copy of *msg* with ``cache_control`` on its content."""

        self._logger.debug(
            "_with_cache_control - msg type: %s - content type: %s",
            type(msg), 
            type(msg.content)
        )

        content = msg.content
        if isinstance(content, str):
            content = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": self._cache_control,
                }
            ]
        elif isinstance(content, list):
            content = list(content)
            last_block = dict(content[-1])
            last_block["cache_control"] = self._cache_control
            content[-1] = last_block

        return msg.__class__(content=content, **{
            k: v for k, v in msg.__dict__.items() if k != "content"
        })
