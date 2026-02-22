"""Main chat screen — tabbed chat sessions + StatusBar."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import TabbedContent, TabPane

from rhizome.tui.widgets.chat_pane import ChatPane
from rhizome.tui.widgets.status_bar import StatusBar


class ChatTabPane(TabPane):
    """A TabPane that composes a ChatPane as its content.

    Stores the full (untruncated) tab name and reactively re-truncates
    the displayed label when ``tab_name_len`` changes.
    """

    def __init__(self, title: str, *, tab_max_length: int = 20, **kwargs) -> None:
        self.full_name: str = title
        self._tab_max_length: int = tab_max_length
        super().__init__(self._truncated_label(), **kwargs)

    def _truncated_label(self) -> str:
        """Return ``full_name`` truncated to ``_tab_max_length`` characters."""
        if len(self.full_name) > self._tab_max_length:
            return self.full_name[: self._tab_max_length] + "\u2026"
        return self.full_name

    def update_tab_max_length(self, new_length: int) -> None:
        """Update the max length and re-truncate the displayed tab label."""
        self._tab_max_length = new_length
        self._update_tab_label()

    def _update_tab_label(self) -> None:
        """Re-truncate ``full_name`` and apply to the Tab widget."""
        tabbed_content = self.screen.query_one("#tabs", TabbedContent)
        tab_widget = tabbed_content.get_tab(self.id)
        tab_widget.label = self._truncated_label()

    def compose(self) -> ComposeResult:
        yield ChatPane()


class ChatScreen(Screen):
    """Primary screen: composes tabbed ChatPanes and a StatusBar."""

    BINDINGS = [
        ("ctrl+c", "cancel_agent", "Cancel agent"),
        ("ctrl+n", "new_tab", "New tab"),
        # priority=True so the screen captures Ctrl+W before focused child
        # widgets (e.g. ChatInput) consume it.
        Binding("ctrl+w", "close_tab", "Close tab", priority=True),
    ]

    DEFAULT_CSS = """
    ChatScreen {
        layout: grid;
        grid-size: 1;
        grid-rows: 1fr auto;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        height: 1fr;
        padding: 0;
    }
    ChatPane {
        height: 1fr;
    }
    #status-bar {
        dock: bottom;
        height: auto;
        background: $surface;
        padding: 0 1;
        border-top: solid rgb(60, 60, 60);
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tab_counter: int = 1

    def compose(self) -> ComposeResult:
        from rhizome.tui.options import Options
        max_len = self.app.options.get(Options.TabMaxLength)  # type: ignore[attr-defined]
        with TabbedContent(id="tabs"):
            yield ChatTabPane("Session 1", tab_max_length=max_len, id="session-1")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        bar = self.query_one("#status-bar", StatusBar)
        self.watch(self.app, "mode", lambda val: setattr(bar, "mode", val))
        self.watch(self.app, "context", lambda val: setattr(bar, "context", val))

    async def _add_tab(self, label: str | None = None) -> None:
        """Create a new chat session tab."""
        self._tab_counter += 1
        tab_id = f"session-{self._tab_counter}"
        tab_label = label or f"Session {self._tab_counter}"
        tabs = self.query_one("#tabs", TabbedContent)
        from rhizome.tui.options import Options
        max_len = self.app.options.get(Options.TabMaxLength)  # type: ignore[attr-defined]
        pane = ChatTabPane(tab_label, tab_max_length=max_len, id=tab_id)
        await tabs.add_pane(pane)
        tabs.active = tab_id

    # Stubbed out for potential future use
    # def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
    #     pass

    def action_cancel_agent(self) -> None:
        self.app.active_chat_pane.cancel_agent()  # type: ignore[attr-defined]

    async def _close_active_tab(self) -> None:
        """Close the active chat session tab (refuses to close the last one)."""
        from rhizome.tui.types import ChatMessageData, Role

        tabs = self.query_one("#tabs", TabbedContent)
        pane_count = len(list(tabs.query(TabPane)))
        if pane_count <= 1:
            self.app.active_chat_pane.append_message(  # type: ignore[attr-defined]
                ChatMessageData(role=Role.SYSTEM, content="Cannot close the last session tab.")
            )
            return
        active_id = tabs.active
        if active_id:
            tabs.remove_pane(active_id)

    def action_close_tab(self) -> None:
        self.run_worker(self._close_active_tab())

    def action_new_tab(self) -> None:
        self.run_worker(self._add_tab())
