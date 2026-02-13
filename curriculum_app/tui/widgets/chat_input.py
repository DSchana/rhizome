"""Multiline chat input: Enter submits, Ctrl+Enter inserts a newline."""

from textual.message import Message
from textual.widgets import TextArea


class ChatInput(TextArea):
    """A TextArea that submits on Enter and inserts newlines on Ctrl+Enter."""

    class Submitted(Message):
        """Posted when the user presses Enter to submit their message."""

        def __init__(self, input: "ChatInput", value: str) -> None:
            super().__init__()
            self.input = input
            self.value = value

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

    def on_mount(self) -> None:
        if self._placeholder:
            self.placeholder = self._placeholder

    def _on_key(self, event) -> None:
        if event.key == "enter":
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(input=self, value=text))
                self.clear()
            event.stop()
            event.prevent_default()
            
        # Ctrl+Enter sends \n (0x0A) in most terminals, which Textual maps
        # to ctrl+j.  Terminals implementing the Kitty keyboard protocol
        # would report "shift+enter" / "ctrl+enter" distinctly, but most
        # terminals (WSL2, default macOS Terminal, etc.) do not.  If Kitty
        # protocol support becomes relevant, add those as additional matches.
        elif event.key == "ctrl+j":
            self.insert("\n")
            event.stop()
            event.prevent_default()
        else:
            super()._on_key(event)  # pyright: ignore[reportUnusedCoroutine]
