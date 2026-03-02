"""InterruptChoices — widget for resolving agent graph interrupts."""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, Label


class InterruptChoices(Widget):
    """Displays an interrupt prompt with option buttons and resolves an asyncio.Future.

    The widget is mounted by ``AgentMessageHarness.on_interrupt()`` and blocks
    the agent stream until the user selects an option.  The selection is
    returned via ``wait_for_selection()``, which awaits an internal
    ``asyncio.Future``.
    """

    DEFAULT_CSS = """
    InterruptChoices {
        height: auto;
        layout: vertical;
        padding: 1 2;
        margin: 1 0;
        background: $surface;
        border: round $accent;
    }
    InterruptChoices .interrupt-prompt {
        margin-bottom: 1;
    }
    InterruptChoices .interrupt-buttons {
        height: auto;
    }
    InterruptChoices Button {
        margin: 0 1 0 0;
    }
    """

    def __init__(
        self,
        prompt: str = "The agent requires your input:",
        options: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._prompt = prompt
        self._options = options or ["Continue", "Cancel"]
        self._future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()

    def compose(self) -> ComposeResult:
        yield Label(self._prompt, classes="interrupt-prompt")
        with Horizontal(classes="interrupt-buttons"):
            for i, option in enumerate(self._options):
                yield Button(option, id=f"interrupt-opt-{i}", variant="primary" if i == 0 else "default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Resolve the future with the selected option."""
        if self._future.done():
            return
        # Extract the option index from the button id
        button_id = event.button.id or ""
        idx = int(button_id.split("-")[-1]) if button_id.startswith("interrupt-opt-") else 0
        value = self._options[idx] if idx < len(self._options) else self._options[0]
        self._future.set_result(value)

    async def wait_for_selection(self) -> Any:
        """Block until the user selects an option. Returns the selected value."""
        return await self._future

    def cancel(self) -> None:
        """Cancel the pending future if not yet resolved."""
        if not self._future.done():
            self._future.cancel()
