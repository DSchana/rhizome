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

        # Walk backwards to find the last decorated message and its ID.
        next_id = 1
        first_undecorated_idx = 0

        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if not isinstance(msg, (HumanMessage, AIMessage)):
                continue
            rid = _get_rhizome_message_id(msg)
            if rid is not None:
                next_id = rid + 1
                first_undecorated_idx = i + 1
                break

        # Walk forward from the boundary, decorating untagged messages.
        updated: list[HumanMessage | AIMessage] = []
        for msg in messages[first_undecorated_idx:]:
            if not isinstance(msg, (HumanMessage, AIMessage)):
                continue
            if _get_rhizome_message_id(msg) is not None:
                continue
            updated.append(_decorate_message(msg, next_id))
            next_id += 1

        if not updated:
            return None

        _logger.debug("Decorated %d message(s), next_id=%d", len(updated), next_id)
        return {"messages": updated}
