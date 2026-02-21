"""Main Textual application."""

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker
from textual.app import App
from textual.reactive import reactive
from textual.widgets import TabbedContent

from rhizome.agent import build_agent
from rhizome.config import get_default_db_path
from rhizome.db import Curriculum, Topic, get_engine, get_session_factory
from rhizome.tui.screens.chat import ChatScreen
from rhizome.tui.state import Mode
from rhizome.tui.widgets.chat_pane import ChatPane


class CurriculumApp(App):
    """Curriculum-app TUI — a chat-based interface for learning and review."""

    TITLE = "rhizome"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    mode: reactive[str] = reactive(Mode.IDLE.value)
    context: reactive[str] = reactive("")

    active_curriculum: Curriculum | None = None
    active_topic: Topic | None = None

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__()
        engine = get_engine(db_path or get_default_db_path())
        self.session_factory: async_sessionmaker = get_session_factory(engine)
        self.agent = build_agent()

    @property
    def active_chat_pane(self) -> ChatPane:
        """Return the ChatPane in the currently active tab."""
        tabs = self.screen.query_one("#tabs", TabbedContent)
        active = tabs.active_pane
        assert active is not None
        return active.query_one(ChatPane)

    def sync_active_session(self) -> None:
        """Mirror the active pane's session state into app-level reactives."""
        try:
            pane = self.active_chat_pane
        except Exception:
            return
        self.active_curriculum = pane.active_curriculum
        self.active_topic = pane.active_topic
        self.mode = pane.session_mode
        self.context = pane.session_context

    def set_mode(self, new_mode: Mode) -> None:
        """Update the current mode on the active pane and sync."""
        pane = self.active_chat_pane
        pane.session_mode = new_mode.value
        self.sync_active_session()

    def update_context(
        self,
        curriculum: Curriculum | None,
        topic: Topic | None,
    ) -> None:
        """Update the active curriculum/topic on the active pane and sync."""
        pane = self.active_chat_pane
        pane.active_curriculum = curriculum
        pane.active_topic = topic
        if curriculum and topic:
            pane.session_context = f"{curriculum.name} > {topic.name}"
        elif curriculum:
            pane.session_context = curriculum.name
        else:
            pane.session_context = ""
        self.sync_active_session()

    def on_mount(self) -> None:
        self.push_screen(ChatScreen())
