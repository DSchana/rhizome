"""Chat message display widget built on Textual's Markdown."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Button, Markdown, Static

from rhizome.tui.colors import Colors
from rhizome.tui.types import Mode, Role


class ChatMessage(Widget):
    """Renders a single chat message with role-based styling and markdown support."""

    DEFAULT_CSS = f"""
    ChatMessage {{
        padding: 1 1;
        height: auto;
    }}
    ChatMessage.user-message {{
        background: {Colors.IDLE_USER_BG};
    }}
    ChatMessage.agent-message {{
        background: {Colors.IDLE_AGENT_BG};
    }}
    ChatMessage.system-message {{
        background: {Colors.IDLE_SYSTEM_BG};
        color: $text-muted;
        padding: 0 1;
    }}
    ChatMessage.learn-mode.user-message {{
        background: {Colors.LEARN_USER_BG};
    }}
    ChatMessage.learn-mode.agent-message {{
        background: {Colors.LEARN_AGENT_BG};
    }}
    ChatMessage.review-mode.user-message {{
        background: {Colors.REVIEW_USER_BG};
    }}
    ChatMessage.review-mode.agent-message {{
        background: {Colors.REVIEW_AGENT_BG};
    }}
    ChatMessage #msg-collapse {{
        dock: right;
        width: 3;
        min-width: 3;
        height: 1;
        background: transparent;
        border: none;
        color: $text-muted;
    }}
    ChatMessage #msg-collapse:hover {{
        color: $text;
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
        Role.USER: "**you:** ",
        Role.AGENT: "**agent:** ",
        Role.SYSTEM: "*system:* ",
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
        yield Markdown(self._prefix + self._body, classes="msg-content")
        if self._role == Role.AGENT:
            yield Static("", id="msg-line-count")

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
        self._collapsed = not self._collapsed
        event.button.label = "▶" if self._collapsed else "▼"
        if self._collapsed:
            self.add_class("--collapsed")
            self.inner_markdown.update(self._prefix + self._truncated_body())
            extra = self._extra_line_count()
            if extra > 0:
                self.query_one("#msg-line-count", Static).update(f"(+{extra} more lines)")
        else:
            self.remove_class("--collapsed")
            self.inner_markdown.update(self._prefix + self._body)

    def update_body(self, body: str) -> None:
        """Update the stored body text (used after streaming completes)."""
        self._body = body
