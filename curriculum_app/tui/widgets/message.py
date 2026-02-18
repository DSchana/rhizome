"""Chat message display widget."""

from textual.widgets import Static


class MessageWidget(Static):
    """Renders a single chat message with role-based styling."""

    DEFAULT_CSS = """
    MessageWidget {
        margin: 0 0 1 0;
        padding: 0 1;
    }
    MessageWidget.user-message {
        background: rgb(31, 31, 31);
    }
    MessageWidget.agent-message {
        background: rgb(24, 24, 24);
    }
    """

    def __init__(self, role: str, content: str) -> None:
        prefix = "you" if role == "user" else "agent"
        super().__init__(f"[bold]{prefix}:[/bold] {content}")
        self.add_class(f"{role}-message")
