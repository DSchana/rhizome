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
    "learn": _compact_rgb(Colors.LEARN_SYSTEM_TEXT),
    "review": _compact_rgb(Colors.REVIEW_SYSTEM_TEXT),
}


class StatusBar(Static):
    """Displays the current mode and active curriculum/topic context."""

    mode: reactive[str] = reactive("idle")
    topic_path: reactive[list[str]] = reactive(list)
    token_usage: reactive[TokenUsageData] = reactive(TokenUsageData)

    # Max characters for the rendered topic path (excluding the "topic: " prefix).
    TOPIC_PATH_MAX = 60

    def render(self) -> Text:
        # -- line 1: topic path --
        _label = "rgb(140,140,140)"
        topic_line = Text()
        topic_line.append("topic: ", style=_label)
        if self.topic_path:
            sep = " > "
            full = sep.join(self.topic_path)
            if len(full) <= self.TOPIC_PATH_MAX:
                topic_line.append(full)
            else:
                # Truncate from the left, keeping as many trailing segments as fit.
                parts = list(self.topic_path)
                while len(parts) > 1 and len(sep.join(parts)) + len("... > ") > self.TOPIC_PATH_MAX:
                    parts.pop(0)
                topic_line.append("... > " + sep.join(parts))
        else:
            topic_line.append("none", style="rgb(100,100,100)")

        # Right-align cache usage on the topic line
        cache_text = Text()
        cache_read = self.token_usage.cache_read_tokens
        cache_create = self.token_usage.cache_creation_tokens
        if cache_read is not None or cache_create is not None:
            cache_text.append(
                f"cache read: {cache_read:,}  create: {cache_create:,}",
                style="rgb(90,90,90)",
            )
            gap = max(self.size.width - len(topic_line.plain) - len(cache_text.plain), 2)
            topic_line.append(" " * gap)
            topic_line.append(cache_text)

        # -- line 2: mode + token usage --
        left = Text()
        left.append("mode: ", style=_label)
        mode_color = _MODE_COLORS.get(self.mode)
        if mode_color:
            left.append(self.mode, style=mode_color)
        else:
            left.append(self.mode)
        left.append("  (shift+tab to cycle)", style="rgb(100,100,100)")

        right = Text()
        if self.token_usage.total_tokens:
            total = self.token_usage.total_tokens

            system_overhead = self.token_usage.breakdown.get(TokenUsageData.BreakdownCategory.SYSTEM)
            tool_overhead = self.token_usage.breakdown.get(TokenUsageData.BreakdownCategory.TOOL_MESSAGES)

            if system_overhead is not None or tool_overhead is not None:
                overhead_parts = []
                if system_overhead is not None:
                    overhead_parts.append((
                        f"system: {system_overhead:,}",
                        "rgb(120,120,120)"
                    ))
                if tool_overhead is not None:
                    overhead_parts.append((
                        f"tools: {tool_overhead:,}",
                        "rgb(220,160,80)",
                    ))

                right.append(f"tokens: {total:,}")
                right.append(" (", style="rgb(100,100,100)")

                for i, (part, color) in enumerate(overhead_parts):
                    right.append(f"{part}", style=color)
                    if i < len(overhead_parts) - 1:
                        right.append(", ", style="rgb(100,100,100)")

                right.append(")", style="rgb(100,100,100)")
            else:
                right.append(f"tokens: {total:,}")

            pct = self.token_usage.usage_percent
            if pct is not None:
                right.append(f"  context usage: {pct:.1f}%")

        gap = max(self.size.width - len(left.plain) - len(right.plain), 2)
        left.append(" " * gap)
        left.append(right)

        return Text.assemble(topic_line, "\n", left)
