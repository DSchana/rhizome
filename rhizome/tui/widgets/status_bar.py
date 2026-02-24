"""Persistent status bar showing the active mode and context."""

from rich.text import Text
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
        right_plain = ""
        if self.token_usage.total_tokens:
            total = self.token_usage.total_tokens
            overhead = self.token_usage.overhead_tokens
            if overhead is not None:
                conversation = total - overhead
                right = f"tokens: {conversation:,} [rgb(120,120,120)](+{overhead:,})[/]"
                right_plain = f"tokens: {conversation:,} (+{overhead:,})"
            else:
                right = f"tokens: {total:,}"
                right_plain = right
            pct = self.token_usage.usage_percent
            if pct is not None:
                suffix = f"  context usage: {pct:.1f}%"
                right += suffix
                right_plain += suffix

        gap = max(self.size.width - len(left) - len(right_plain), 2)
        return left + " " * gap + right
