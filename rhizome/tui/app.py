"""Main Textual application."""

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker
from textual.app import App
from textual.reactive import reactive

from rhizome.agent import build_agent
from rhizome.config import get_default_db_path
from rhizome.db import Curriculum, Topic, get_engine, get_session_factory
from rhizome.tui.screens.chat import ChatScreen
from rhizome.tui.state import Mode


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

    def set_mode(self, new_mode: Mode) -> None:
        """Update the current mode and sync the reactive property."""
        self.mode = new_mode.value

    def update_context(
        self,
        curriculum: Curriculum | None,
        topic: Topic | None,
    ) -> None:
        """Update the active curriculum/topic and sync the context label."""
        self.active_curriculum = curriculum
        self.active_topic = topic
        if curriculum and topic:
            self.context = f"{curriculum.name} > {topic.name}"
        elif curriculum:
            self.context = curriculum.name
        else:
            self.context = ""

    def on_mount(self) -> None:
        self.push_screen(ChatScreen())
