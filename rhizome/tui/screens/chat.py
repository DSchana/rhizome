"""Main chat screen — thin wrapper around ChatPane + StatusBar."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen

from rhizome.tui.widgets.chat_pane import ChatPane
from rhizome.tui.widgets.status_bar import StatusBar


class ChatScreen(Screen):
    """Primary screen: composes a ChatPane and a StatusBar."""

    BINDINGS = [("ctrl+c", "cancel_agent", "Cancel agent")]

    DEFAULT_CSS = """
    ChatScreen {
        layout: grid;
        grid-size: 1;
        grid-rows: 1fr auto;
    }
    #status-bar {
        dock: bottom;
        height: auto;
        background: $surface;
        padding: 0 1;
        border-top: solid rgb(60, 60, 60);
    }
    """

    def compose(self) -> ComposeResult:
        yield ChatPane(id="chat-pane")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        bar = self.query_one("#status-bar", StatusBar)
        self.watch(self.app, "mode", lambda val: setattr(bar, "mode", val))
        self.watch(self.app, "context", lambda val: setattr(bar, "context", val))

    def action_cancel_agent(self) -> None:
        self.query_one("#chat-pane", ChatPane).cancel_agent()
