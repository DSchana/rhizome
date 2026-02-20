"""Multiline chat input: Enter submits, Ctrl+Enter inserts a newline."""

from textual.message import Message
from textual.widgets import TextArea

from rhizome.tui.commands import COMMANDS, parse_input


class ChatInput(TextArea):
    """A TextArea that submits on Enter and inserts newlines on Ctrl+Enter."""

    class Submitted(Message):
        """Posted when the user presses Enter to submit their message."""

        def __init__(self, input: "ChatInput", value: str) -> None:
            super().__init__()
            self.input = input
            self.value = value

    class FocusTreeRequested(Message):
        """Posted when the user presses Ctrl+Enter with an empty input."""

    class PaletteNavigate(Message):
        """Posted to move the palette selection."""

        def __init__(self, delta: int) -> None:
            super().__init__()
            self.delta = delta

    class PaletteConfirm(Message):
        """Posted when the user presses Tab to confirm a palette selection."""

    def __init__(
        self,
        *,
        placeholder: str = "",
        id: str | None = None,
    ) -> None:
        super().__init__(
            show_line_numbers=False,
            tab_behavior="focus",
            id=id,
        )
        self._placeholder = placeholder
        self.palette_active = False

    def on_mount(self) -> None:
        if self._placeholder:
            self.placeholder = self._placeholder

    def _on_key(self, event) -> None:
        if event.key == "enter":
            text = self.text.strip()
            if self.palette_active and not self._is_complete_command(text):
                self.post_message(self.PaletteConfirm())
                event.stop()
                event.prevent_default()
                return

            if text:
                self.post_message(self.Submitted(input=self, value=text))
                self.clear()
            event.stop()
            event.prevent_default()

        elif event.key == "tab" and self.palette_active:
            self.post_message(self.PaletteConfirm())
            event.stop()
            event.prevent_default()

        elif event.key in ("up", "down") and self.palette_active:
            delta = -1 if event.key == "up" else 1
            self.post_message(self.PaletteNavigate(delta=delta))
            event.stop()
            event.prevent_default()

        # Ctrl+Enter sends \n (0x0A) in most terminals, which Textual maps
        # to ctrl+j.  Terminals implementing the Kitty keyboard protocol
        # would report "shift+enter" / "ctrl+enter" distinctly, but most
        # terminals (WSL2, default macOS Terminal, etc.) do not.  If Kitty
        # protocol support becomes relevant, add those as additional matches.
        elif event.key == "ctrl+j":
            if not self.text.strip():
                self.post_message(self.FocusTreeRequested())
            else:
                self.insert("\n")
            event.stop()
            event.prevent_default()
        else:
            super()._on_key(event)  # pyright: ignore[reportUnusedCoroutine]

    @staticmethod
    def _is_complete_command(text: str) -> bool:
        """Return True if *text* is a fully typed known command (e.g. '/explore')."""
        parsed = parse_input(text)
        if parsed is None:
            return False
        return parsed.name in COMMANDS or parsed.name == "quit"
