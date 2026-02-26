"""Persistent status bar showing the active mode and context."""

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from rhizome.tui.colors import Colors
from rhizome.tui.types import TokenUsageData

def _compact_rgb(s: str) -> str:
    """Strip spaces from RGB strings so Rich can parse them."""
    return s.replace(" ", "")

_MODE_COLORS: dict[str, str] = {
    "learn": _compact_rgb(Colors.LEARN_AGENT_BORDER),
    "review": _compact_rgb(Colors.REVIEW_AGENT_BORDER),
}


class StatusBar(Static):
    """Displays the current mode and active curriculum/topic context."""

    mode: reactive[str] = reactive("idle")
    context: reactive[str] = reactive("")
    token_usage: reactive[TokenUsageData] = reactive(TokenUsageData)

    def render(self) -> Text:
        # -- left: mode (coloured) + context + hint --
        result = Text("mode: ")
        mode_color = _MODE_COLORS.get(self.mode)
        if mode_color:
            result.append(self.mode, style=mode_color)
        else:
            result.append(self.mode)

        hint = Text("  (shift+tab to cycle)", style="rgb(100,100,100)")

        if self.context:
            result.append(f"  [{self.context}]")

        result.append(hint)

        left_len = len(result.plain)

        # -- right: token usage --
        right = Text()
        if self.token_usage.total_tokens:
            total = self.token_usage.total_tokens
            overhead = self.token_usage.overhead_tokens
            if overhead is not None:
                conversation = total - overhead
                right.append(f"tokens: {conversation:,} ")
                right.append(f"(+{overhead:,})", style="rgb(120,120,120)")
            else:
                right.append(f"tokens: {total:,}")
            pct = self.token_usage.usage_percent
            if pct is not None:
                right.append(f"  context usage: {pct:.1f}%")

        gap = max(self.size.width - left_len - len(right.plain), 2)
        result.append(" " * gap)
        result.append(right)
        return result
