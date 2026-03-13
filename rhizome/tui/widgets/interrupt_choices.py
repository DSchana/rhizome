"""InterruptChoices — widget for resolving agent graph interrupts."""

from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, Static

class InterruptChoices(Widget, can_focus=True):
    """Displays an interrupt prompt with a navigable list of options.

    The widget is mounted by ``AgentMessageHarness.on_interrupt()`` and blocks
    the agent stream until the user selects an option.  The selection is
    returned via ``wait_for_selection()``, which awaits an internal
    ``asyncio.Future``.

    Navigation: Up/Down to move highlight, Enter to select.
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Move up", show=False),
        Binding("down", "cursor_down", "Move down", show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    DEFAULT_CSS = """
    InterruptChoices {
        height: auto;
        layout: vertical;
        padding: 0 2;
        margin: 1 0;
    }
    InterruptChoices .interrupt-prompt {
        margin-bottom: 1;
    }
    """

    cursor: reactive[int] = reactive(0)

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

    @classmethod
    def from_interrupt(cls, value: dict[str, Any]) -> InterruptChoices:
        """Construct from an interrupt value dict."""
        return cls(
            prompt=value.get("message", "The agent requires your input:"),
            options=value.get("options"),
        )

    def compose(self) -> ComposeResult:
        yield Label(self._prompt, classes="interrupt-prompt")
        yield Static(id="interrupt-options")
        yield Static("  (ctrl+c to cancel)", id="interrupt-hint")

    def on_mount(self) -> None:
        self._render_options()
        self.query_one("#interrupt-hint", Static).styles.color = "rgb(100,100,100)"
        self.focus()
        self.scroll_visible(animate=False)
        self.call_after_refresh(self._render_options)

    def watch_cursor(self) -> None:
        self._render_options()

    def on_focus(self) -> None:
        if not self._future.done():
            self._render_options()

    def on_blur(self) -> None:
        if not self._future.done():
            self._render_options()

    def _render_options(self) -> None:
        focused = self.has_focus
        text = Text()
        for i, option in enumerate(self._options):
            if i > 0:
                text.append("\n")
            label = f"  {i + 1}. {option}"
            if not focused:
                text.append(label, style="rgb(100,100,100)")
            elif i == self.cursor:
                text.append(label, style="bold white")
            else:
                text.append(label, style="rgb(100,100,100)")
        self.query_one("#interrupt-options", Static).update(text)

    def action_cursor_up(self) -> None:
        if not self._future.done():
            self.cursor = (self.cursor - 1) % len(self._options)

    def action_cursor_down(self) -> None:
        if not self._future.done():
            self.cursor = (self.cursor + 1) % len(self._options)

    def action_select(self) -> None:
        if self._future.done():
            return
        selected = self._options[self.cursor]
        self._future.set_result(selected)
        display = Text()
        display.append(f"  you selected: {selected}", style="rgb(100,100,100)")
        self.query_one("#interrupt-options", Static).update(display)
        self.query_one("#interrupt-hint", Static).update("")

    async def wait_for_selection(self) -> Any:
        """Block until the user selects an option. Returns the selected value."""
        return await self._future

    def cancel(self) -> None:
        """Cancel the pending future if not yet resolved."""
        if not self._future.done():
            self._future.cancel()
