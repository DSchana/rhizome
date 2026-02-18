"""Main Textual application."""

from textual.app import App
from textual.reactive import reactive

from curriculum_app.db import Curriculum, Topic
from curriculum_app.tui.screens.chat import ChatScreen
from curriculum_app.tui.state import Mode


class CurriculumApp(App):
    """Curriculum-app TUI — a chat-based interface for learning and review."""

    TITLE = "curriculum-app"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    mode: reactive[str] = reactive(Mode.IDLE.value)
    context: reactive[str] = reactive("")

    active_curriculum: Curriculum | None = None
    active_topic: Topic | None = None

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
