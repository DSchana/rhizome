"""Persistent status bar showing the active mode and context."""

from textual.reactive import reactive
from textual.widgets import Static

from rhizome.tui.types import TokenUsageData


class StatusBar(Static):
    """Displays the current mode and active curriculum/topic context."""

    mode: reactive[str] = reactive("idle")
    context: reactive[str] = reactive("")
    token_usage: reactive[TokenUsageData] = reactive(TokenUsageData)

    def render(self) -> str:
        left_parts: list[str] = [f"mode: {self.mode}"]
        if self.context:
            left_parts.append(f"[{self.context}]")
        left = "  ".join(left_parts)

        right = ""
        if self.token_usage.total_tokens:
            right = f"tokens: {self.token_usage.total_tokens:,}"
            pct = self.token_usage.usage_percent
            if pct is not None:
                right += f" ({pct:.1f}%)"

        gap = max(self.size.width - len(left) - len(right), 2)
        return left + " " * gap + right
