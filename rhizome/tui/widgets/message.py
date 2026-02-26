"""Chat message display widget built on Textual's Markdown."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Button, Markdown, Static

from rhizome.tui.colors import Colors
from rhizome.tui.types import Mode, Role


COLLAPSE_LINE_THRESHOLD = 4
"""Messages with more than this many lines show a collapse button."""


class ChatMessage(Widget):
    """Renders a single chat message with role-based styling and markdown support."""

    DEFAULT_CSS = f"""
    ChatMessage {{
        padding: 1 2;
        height: auto;
    }}
    ChatMessage.user-message {{
        background: {Colors.USER_BG};
        margin: 0 2;
        padding: 1 2 0 2;
    }}
    ChatMessage.agent-message {{
        padding: 1 2 0 2;
    }}
    ChatMessage.system-message {{
        color: $text-muted;
        padding: 1 2 0 2;
    }}
    ChatMessage.system-message.--after-system {{
        padding: 0 2 0 2;
    }}
    ChatMessage.error-message {{
        color: {Colors.SYSTEM_ERROR};
        padding: 1 2 0 2;
    }}
    ChatMessage.error-message Markdown {{
        color: {Colors.SYSTEM_ERROR};
    }}
    ChatMessage.learn-mode.agent-message {{
        border: round {Colors.LEARN_AGENT_BORDER};
        margin: 0 2;
    }}
    ChatMessage.review-mode.agent-message {{
        border: round {Colors.REVIEW_AGENT_BORDER};
        margin: 0 2;
    }}
    ChatMessage.agent-message.--commit-selectable {{
        border: round {Colors.COMMIT_SELECTABLE};
    }}
    ChatMessage.agent-message.--commit-cursor {{
        border: round {Colors.COMMIT_CURSOR};
    }}
    ChatMessage.agent-message.--commit-selected {{
        border: round {Colors.COMMIT_SELECTED};
    }}
    ChatMessage.agent-message.--commit-selected.--commit-cursor {{
        border: round {Colors.COMMIT_SELECTED_CURSOR};
    }}
    ChatMessage .commit-checkbox {{
        dock: left;
        width: 3;
        min-width: 3;
        height: 1;
        padding: 0;
    }}
    ChatMessage #msg-collapse {{
        dock: right;
        width: auto;
        min-width: 3;
        height: 1;
        background: transparent;
        border: none;
        color: $text-muted;
        display: none;
    }}
    ChatMessage.--collapsible #msg-collapse {{
        display: block;
    }}
    ChatMessage #msg-collapse:hover {{
        color: $text;
    }}
    ChatMessage .msg-prefix {{
        height: auto;
    }}
    ChatMessage .msg-content {{
        width: 1fr;
    }}
    ChatMessage #msg-line-count {{
        display: none;
        color: $text-muted 50%;
        padding: 0 0 0 1;
    }}
    ChatMessage.--collapsed #msg-line-count {{
        display: block;
    }}
    """

    ROLE_PREFIXES = {
        Role.USER: f"[bold {Colors.USER_PREFIX}]you:[/bold {Colors.USER_PREFIX}] ",
        Role.AGENT: f"[bold {Colors.AGENT_PREFIX}]agent:[/bold {Colors.AGENT_PREFIX}] ",
        Role.SYSTEM: f"[{Colors.SYSTEM_PREFIX}]system:[/{Colors.SYSTEM_PREFIX}] ",
        Role.ERROR: f"[bold {Colors.SYSTEM_ERROR}]error:[/bold {Colors.SYSTEM_ERROR}] ",
    }

    def __init__(self, role: Role, content: str = "", mode: Mode = Mode.IDLE) -> None:
        super().__init__()
        self._role = role
        self._prefix = self.ROLE_PREFIXES.get(role, "")
        self._body = content
        self._collapsed = False
        self.add_class(f"{role.value}-message")
        if mode == Mode.LEARN:
            self.add_class("learn-mode")
        elif mode == Mode.REVIEW:
            self.add_class("review-mode")

    def compose(self) -> ComposeResult:
        if self._role == Role.AGENT:
            yield Button("▼", id="msg-collapse")
        yield Static(self._prefix, classes="msg-prefix")
        yield Markdown(self._body, classes="msg-content")
        if self._role == Role.AGENT:
            yield Static("", id="msg-line-count")

    def on_mount(self) -> None:
        self._check_collapsible()

    @property
    def inner_markdown(self) -> Markdown:
        """Access the inner Markdown widget."""
        return self.query_one(".msg-content", Markdown)

    @property
    def content_text(self) -> str:
        """The raw body text (without the role prefix)."""
        return self._body

    def _truncated_body(self) -> str:
        """Return the first line of _body, truncated with ellipsis."""
        first_line = self._body.split("\n", 1)[0]
        has_more = "\n" in self._body or len(first_line) > 80
        if len(first_line) > 80:
            first_line = first_line[:80]
        return first_line + "..." if has_more else first_line

    def _extra_line_count(self) -> int:
        """Count of lines beyond the first in _body."""
        lines = self._body.split("\n")
        return len(lines) - 1

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "msg-collapse":
            return
        event.stop()
        self.toggle_collapse()

    def toggle_collapse(self) -> None:
        """Programmatically toggle the collapsed state of this message."""
        if not self.has_class("--collapsible"):
            return
        self._collapsed = not self._collapsed
        self._update_collapse_label()
        if self._collapsed:
            self.add_class("--collapsed")
            self.inner_markdown.update(self._truncated_body())
            extra = self._extra_line_count()
            if extra > 0:
                self.query_one("#msg-line-count", Static).update(f"(+{extra} more lines)")
        else:
            self.remove_class("--collapsed")
            self.inner_markdown.update(self._body)

    def _check_collapsible(self) -> None:
        """Show or hide the collapse button based on line count."""
        if self._role == Role.AGENT and self._body.count("\n") >= COLLAPSE_LINE_THRESHOLD:
            self.add_class("--collapsible")
        else:
            self.remove_class("--collapsible")

    def _update_collapse_label(self) -> None:
        """Update the collapse button label, appending a shortcut hint if appropriate."""
        if self._role != Role.AGENT:
            return
        btn = self.query_one("#msg-collapse", Button)
        arrow = "▶" if self._collapsed else "▼"
        if self.has_class("--show-shortcut"):
            btn.label = f"(ctrl+t) {arrow}"
        else:
            btn.label = arrow

    def update_body(self, body: str) -> None:
        """Update the stored body text (used after streaming completes)."""
        self._body = body
        self._check_collapsible()
