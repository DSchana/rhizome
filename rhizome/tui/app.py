"""Main Textual application."""

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker
from textual.app import App
from textual.reactive import reactive
from textual.widgets import TabbedContent

from rhizome.agent import build_agent
from rhizome.config import get_default_db_path
from rhizome.db import get_engine, get_session_factory
from rhizome.tui.screens.chat import ChatScreen
from rhizome.tui.widgets.chat_pane import ChatPane


class CurriculumApp(App):
    """Curriculum-app TUI — a chat-based interface for learning and review."""

    TITLE = "rhizome"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__()
        engine = get_engine(db_path or get_default_db_path())
        self.session_factory: async_sessionmaker = get_session_factory(engine)
        self.agent = build_agent()

    @property
    def active_chat_pane(self) -> ChatPane | None:
        """Return the ChatPane in the currently active tab."""
        tabs = self.screen.query_one("#tabs", TabbedContent)
        active = tabs.active_pane
        if active is None:
            return active
        return active.query_one(ChatPane)

    def on_mount(self) -> None:
        self.push_screen(ChatScreen())
