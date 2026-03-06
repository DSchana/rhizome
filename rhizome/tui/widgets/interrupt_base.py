"""Base protocol for interrupt widgets used by AgentMessageHarness."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


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
