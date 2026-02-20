"""Chat message display widget built on Textual's Markdown."""

from textual.widgets import Markdown


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
    """

    def __init__(self, role: str, content: str = "") -> None:
        self._role = role
        self._prefix = "**you:** " if role == "user" else "**agent:** "
        self._body = content
        super().__init__(self._prefix + self._body)
        self.add_class(f"{role}-message")

    @property
    def content_text(self) -> str:
        """The raw body text (without the role prefix)."""
        return self._body
