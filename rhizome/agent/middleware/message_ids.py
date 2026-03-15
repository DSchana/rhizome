"""Middleware that assigns persistent, visible IDs to human and AI messages.

Each ``HumanMessage`` and ``AIMessage`` is decorated with a ``[MSG-N]`` prefix
in its content and tagged in ``additional_kwargs["rhizome"]["message_id"]`` so
the LLM can reference specific messages by ID without regurgitating content.

The decoration is **idempotent** — already-tagged messages (detected via
``additional_kwargs``, not content inspection) are skipped.  It is also
**permanent** — state updates from ``before_model`` flow through the
``add_messages`` reducer, which replaces messages by ``id`` in-place,
persisting the decorated content in the checkpoint.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents.middleware.types import AgentMiddleware

from rhizome.logs import get_logger

_logger = get_logger("agent.middleware.message_ids")

_RHIZOME_KEY = "rhizome"
_MESSAGE_ID_KEY = "message_id"


def _is_decoratable(msg) -> bool:
    """Return True if *msg* should receive a ``[MSG-N]`` decoration.

    Only ``HumanMessage`` and ``AIMessage`` are candidates.  ``AIMessage``s
    that carry ``tool_calls`` are excluded — they are tool invocations, not
    conversational messages, and decorating them produces a spurious state
    update that surfaces as a duplicate event in the update stream.
    """
    if isinstance(msg, HumanMessage):
        return True
    if isinstance(msg, AIMessage):
        return not msg.tool_calls
    return False


def _get_rhizome_message_id(msg) -> int | None:
    """Read the rhizome message ID from a message's additional_kwargs, if present."""
    return msg.additional_kwargs.get(_RHIZOME_KEY, {}).get(_MESSAGE_ID_KEY)


def _decorate_message(msg: HumanMessage | AIMessage, message_id: int):
    """Return a copy of *msg* with a ``[MSG-N]`` prefix and rhizome metadata."""
    prefix = f"[MSG-{message_id}]"
    content = msg.content

    if isinstance(content, str):
        new_content = f"{prefix} {content}"
    elif isinstance(content, list):
        new_content = [{"type": "text", "text": prefix}] + list(content)
    else:
        new_content = f"{prefix} {content}"

    new_kwargs = {**msg.additional_kwargs, _RHIZOME_KEY: {_MESSAGE_ID_KEY: message_id}}
    return msg.model_copy(update={"content": new_content, "additional_kwargs": new_kwargs})


class MessageIdMiddleware(AgentMiddleware):
    """Assign sequential ``[MSG-N]`` IDs to human and AI messages.

    Uses ``before_model`` / ``abefore_model`` so that the decorated messages
    are persisted in the checkpoint via the ``add_messages`` reducer.

    Detection of already-decorated messages is done via
    ``additional_kwargs["rhizome"]["message_id"]``, never by inspecting
    message content.
    """

    def before_model(self, state, runtime) -> dict[str, Any] | None:
        return self._assign_ids(state)

    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        return self._assign_ids(state)

    def _assign_ids(self, state) -> dict[str, Any] | None:
        messages = state.get("messages", [])

        _logger.debug(
            "=== MessageIdMiddleware._assign_ids called with %d message(s) ===",
            len(messages),
        )

        # Log a compact summary of all messages in state
        for i, msg in enumerate(messages):
            msg_type = type(msg).__name__
            rid = _get_rhizome_message_id(msg) if hasattr(msg, "additional_kwargs") else None
            content_preview = ""
            if hasattr(msg, "content"):
                c = msg.content
                if isinstance(c, str):
                    content_preview = c[:80].replace("\n", "\\n")
                elif isinstance(c, list) and c:
                    first = c[0]
                    if isinstance(first, dict):
                        content_preview = str(first.get("text", first.get("type", "")))[:80]
                    else:
                        content_preview = str(first)[:80]
            msg_id = getattr(msg, "id", None)
            tool_call_id = getattr(msg, "tool_call_id", None)

            extra = ""
            if tool_call_id:
                extra = f" tool_call_id={tool_call_id}"
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tc_names = [tc.get("name", "?") for tc in msg.tool_calls]
                extra += f" tool_calls={tc_names}"

            _logger.debug(
                "  [%d] %s (id=%s, rhizome_id=%s%s): %s",
                i, msg_type, msg_id, rid, extra, content_preview,
            )

        # Walk backwards to find the last decorated message and its ID.
        next_id = 1
        first_undecorated_idx = 0

        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if not _is_decoratable(msg):
                continue
            rid = _get_rhizome_message_id(msg)
            if rid is not None:
                next_id = rid + 1
                first_undecorated_idx = i + 1
                _logger.debug(
                    "Last decorated msg at index %d (rhizome_id=%d), scanning from %d, next_id=%d",
                    i, rid, first_undecorated_idx, next_id,
                )
                break

        # Walk forward from the boundary, decorating untagged messages.
        updated: list[HumanMessage | AIMessage] = []
        for i, msg in enumerate(messages[first_undecorated_idx:], start=first_undecorated_idx):
            if not _is_decoratable(msg):
                _logger.debug(
                    "  Skipping [%d] %s (%s)",
                    i, type(msg).__name__,
                    "tool-call AIMessage" if isinstance(msg, AIMessage) and msg.tool_calls
                    else "not Human/AI",
                )
                continue
            if _get_rhizome_message_id(msg) is not None:
                _logger.debug(
                    "  Skipping [%d] %s (already decorated, rhizome_id=%s)",
                    i, type(msg).__name__, _get_rhizome_message_id(msg),
                )
                continue
            _logger.debug(
                "  Decorating [%d] %s → MSG-%d (langchain id=%s)",
                i, type(msg).__name__, next_id, getattr(msg, "id", None),
            )
            updated.append(_decorate_message(msg, next_id))
            next_id += 1

        if not updated:
            _logger.debug("No messages to decorate, returning None")
            return None

        _logger.debug(
            "Returning %d decorated message(s) for add_messages reducer, next_id=%d",
            len(updated), next_id,
        )
        return {"messages": updated}
