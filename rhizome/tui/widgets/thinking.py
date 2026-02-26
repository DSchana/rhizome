"""Animated 'thinking...' spinner widget."""

from textual.widgets import Static

_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class ThinkingIndicator(Static):
    """A small braille-spinner + 'thinking...' label."""

    DEFAULT_CSS = """
    ThinkingIndicator {
        height: 1;
        margin-top: 1;
        margin-bottom: 1;
        padding: 0 0 0 4;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__(f"{_FRAMES[0]} thinking...")
        self._frame = 0

    def on_mount(self) -> None:
        self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(_FRAMES)
        self.content = f"{_FRAMES[self._frame]} thinking..."
