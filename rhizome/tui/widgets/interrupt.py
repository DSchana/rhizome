"""Base protocol for interrupt widgets used by AgentMessageHarness."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from textual.message import Message


class WidgetDeactivated(Message):
    """Posted by interactive widgets when they are no longer accepting input.

    ChatPane listens for this to remove the widget from the navigable
    active-widget stack.
    """

    def __init__(self, sender: Any) -> None:
        super().__init__()
        self.sender_widget = sender


@runtime_checkable
class InterruptWidget(Protocol):
    """Protocol that all interrupt widgets must satisfy.

    Interrupt widgets are mounted by ``AgentMessageHarness.on_interrupt()``
    and block the agent stream until the user provides input.
    """

    async def wait_for_selection(self) -> Any:
        """Block until the user resolves the interrupt. Returns the result value."""
        ...

    def cancel(self) -> None:
        """Cancel the pending interrupt if not yet resolved."""
        ...
