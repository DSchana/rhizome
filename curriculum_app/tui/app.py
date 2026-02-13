"""Main Textual application."""

from textual.app import App

from curriculum_app.tui.screens.chat import ChatScreen
from curriculum_app.tui.state import AppState


class CurriculumApp(App):
    """Curriculum-app TUI — a chat-based interface for learning and review."""

    TITLE = "curriculum-app"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.state = AppState()

    def on_mount(self) -> None:
        self.push_screen(ChatScreen(self.state))
