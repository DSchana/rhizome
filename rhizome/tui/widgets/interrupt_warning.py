"""InterruptWarning — widget for resolving dangerous-action confirmation interrupts.

Displays a warning icon and highlighted message, with Approve/Deny as default
options plus any additional options from the interrupt config. After selection,
the widget removes itself from the DOM (the harness keeps only the chosen option
text visible).
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class InterruptWarning(Widget, can_focus=True):
    """Displays a warning prompt with Approve / Deny and optional extra choices.

    Navigation: Up/Down to move highlight, Enter to select.
    After selection the widget collapses to a single line showing the choice,
    then removes the warning text from the display.
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Move up", show=False),
        Binding("down", "cursor_down", "Move down", show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    DEFAULT_CSS = """
    InterruptWarning {
        height: auto;
        layout: vertical;
        padding: 0 2;
        margin: 1 0;
    }
    InterruptWarning .warning-icon {
        color: rgb(220, 160, 50);
    }
    InterruptWarning .warning-message {
        color: rgb(220, 160, 50);
        margin-bottom: 1;
    }
    """

    cursor: reactive[int] = reactive(0)

    def __init__(
        self,
        message: str = "The agent has requested a dangerous action.",
        options: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._message = message
        self._options = ["Approve", "Deny"] + (options or [])
        self._future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()

    @classmethod
    def from_interrupt(cls, value: dict[str, Any]) -> InterruptWarning:
        """Construct from an interrupt value dict."""
        return cls(
            message=value.get("message", "The agent has requested a dangerous action."),
            options=value.get("options"),
        )

    def compose(self) -> ComposeResult:
        yield Static("⚠", classes="warning-icon")
        yield Static(self._message, classes="warning-message")
        yield Static(id="warning-options")
        yield Static("  (ctrl+c to cancel)", id="warning-hint")

    def on_mount(self) -> None:
        self._render_options()
        self.query_one("#warning-hint", Static).styles.color = "rgb(100,100,100)"
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
        self.query_one("#warning-options", Static).update(text)

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
        # Collapse: hide everything except a brief confirmation line
        self.query_one(".warning-icon", Static).display = False
        self.query_one(".warning-message", Static).display = False
        display = Text()
        display.append(f"  you selected: {selected}", style="rgb(100,100,100)")
        self.query_one("#warning-options", Static).update(display)
        self.query_one("#warning-hint", Static).update("")

    async def wait_for_selection(self) -> Any:
        """Block until the user selects an option. Returns the selected value."""
        return await self._future

    def cancel(self) -> None:
        """Cancel the pending future if not yet resolved."""
        if not self._future.done():
            self._future.cancel()
