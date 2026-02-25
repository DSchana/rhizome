"""ToolCallList — renders a collapsible tree of tool call names with box-drawing characters."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Static


class ToolCallList(Widget, can_focus=True):
    """Displays an ordered list of tool call names using Unicode box-drawing."""

    BINDINGS = [
        Binding("enter", "toggle_collapse", "Toggle collapse", show=False),
    ]

    DEFAULT_CSS = """
    ToolCallList {
        color: $text-muted;
        margin-top: 1;
        margin-left: 2;
        padding: 1 2;
        height: auto;
        width: auto;
        min-width: 20;
        max-width: 60;
        border-title-color: $text-muted;
    }
    ToolCallList #tool-content {
        width: auto;
    }
    ToolCallList.--collapsed {
        padding: 0 2;
    }
    ToolCallList.--collapsed #tool-content {
        display: none;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tools: list[str] = []
        self._collapsed = False
        self._update_title()

    def compose(self) -> ComposeResult:
        yield Static("", id="tool-content")

    def _update_title(self) -> None:
        if self._collapsed:
            count = len(self._tools)
            s = "s" if count != 1 else ""
            title = f"{count} tool call{s} (click to expand...) ▶"
        else:
            title = "tool calls ▼"
        self.border_title = title
        # +6 accounts for border chars (┌─ … ─┐) and padding
        self.styles.min_width = len(title) + 6

    def add_tool(self, name: str) -> None:
        """Append a tool name and re-render."""
        self._tools.append(name)
        self._render_list()

    def _render_list(self) -> None:
        lines = []
        for i, name in enumerate(self._tools):
            prefix = "└── " if i == len(self._tools) - 1 else "├── "
            lines.append(f"{prefix}{name}")
        self.query_one("#tool-content", Static).update("\n".join(lines))

    def action_toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self._update_title()
        self.toggle_class("--collapsed")

    def on_click(self) -> None:
        self.action_toggle_collapse()
