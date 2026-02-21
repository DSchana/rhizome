"""Chat message display widget built on Textual's Markdown."""

from textual.widgets import Markdown

from rhizome.tui.types import Role


class ChatMessage(Markdown):
    """Renders a single chat message with role-based styling and markdown support."""

    DEFAULT_CSS = """
    ChatMessage {
        padding: 1 1;
    }
    ChatMessage.user-message {
        background: rgb(31, 31, 31);
    }
    ChatMessage.agent-message {
        background: rgb(40, 40, 40);
    }
    ChatMessage.system-message {
        background: rgb(35, 35, 45);
        color: $text-muted;
        padding: 0 1;
    }
    """

    ROLE_PREFIXES = {
        Role.USER: "**you:** ",
        Role.AGENT: "**agent:** ",
        Role.SYSTEM: "*system:* ",
    }

    def __init__(self, role: Role, content: str = "") -> None:
        self._role = role
        self._prefix = self.ROLE_PREFIXES.get(role, "")
        self._body = content
        super().__init__(self._prefix + self._body)
        self.add_class(f"{role.value}-message")

    @property
    def content_text(self) -> str:
        """The raw body text (without the role prefix)."""
        return self._body
