"""Persistent status bar showing the active mode and context."""

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class StatusBar(Static):
    """Displays the current mode and active curriculum/topic context."""

    mode: reactive[str] = reactive("idle")
    context: reactive[str] = reactive("")

    def render(self) -> str:
        parts: list[str] = [f"mode: {self.mode}"]
        if self.context:
            parts.append(f"[{self.context}]")
        return "  ".join(parts)
