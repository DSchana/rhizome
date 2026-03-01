"""Main chat screen — tabbed chat sessions + StatusBar."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import TabbedContent, TabPane

from rhizome.tui.options import Options
from rhizome.tui.types import ChatMessageData, Mode, Role
from rhizome.tui.widgets.agent_message_harness import AgentMessageHarness
from rhizome.tui.widgets.chat_pane import ChatPane
from rhizome.tui.widgets.logging_pane import LoggingPane
from rhizome.tui.widgets.message import ChatMessage


class LogTabPane(TabPane):
    """A TabPane that composes a LoggingPane for viewing log output."""

    LOG_TAB_ID = "logs-tab"

    def __init__(self, *, tab_max_length: int = 20, **kwargs) -> None:
        self.full_name: str = "Logs"
        self._tab_max_length: int = tab_max_length
        super().__init__(self._truncated_label(), id=self.LOG_TAB_ID, **kwargs)

    def _truncated_label(self) -> str:
        if len(self.full_name) > self._tab_max_length:
            return self.full_name[: self._tab_max_length] + "\u2026"
        return self.full_name

    def update_tab_max_length(self, new_length: int) -> None:
        self._tab_max_length = new_length
        tabbed_content = self.screen.query_one("#tabs", TabbedContent)
        tab_widget = tabbed_content.get_tab(self.id)
        tab_widget.label = self._truncated_label()

    def compose(self) -> ComposeResult:
        yield LoggingPane()


class ChatTabPane(TabPane):
    """A TabPane that composes a ChatPane as its content.

    Stores the full (untruncated) tab name and reactively re-truncates
    the displayed label when ``tab_name_len`` changes.
    """

    def __init__(self, title: str, *, tab_max_length: int = 20, show_welcome: bool = False, **kwargs) -> None:
        self.full_name: str = title
        self._tab_max_length: int = tab_max_length
        self._show_welcome = show_welcome
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
        yield ChatPane(show_welcome=self._show_welcome)


class ChatScreen(Screen):
    """Primary screen: composes tabbed ChatPanes and a StatusBar."""

    BINDINGS = [
        ("ctrl+c", "cancel_agent", "Cancel agent"),
        ("ctrl+n", "new_tab", "New tab"),
        # priority=True so the screen captures Ctrl+W before focused child
        # widgets (e.g. ChatInput) consume it.
        Binding("ctrl+w", "close_tab", "Close tab", priority=True),
        Binding("ctrl+pagedown", "next_tab", "Next tab", show=False, priority=True),
        Binding("ctrl+pageup", "prev_tab", "Previous tab", show=False, priority=True),
        Binding("ctrl+l", "refocus_input", "Refocus input", show=False, priority=True),
        Binding("ctrl+t", "toggle_last_agent_message", "Toggle agent msg", show=False, priority=True),
        Binding("ctrl+o", "toggle_last_tool_call", "Toggle tool call", show=False, priority=True),
        Binding("shift+tab", "cycle_mode", "Cycle mode", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    ChatScreen {
        layout: grid;
        grid-size: 1;
        grid-rows: 1fr;
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
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tab_counter: int = 1

    def compose(self) -> ComposeResult:
        max_len = self.app.options.get(Options.TabMaxLength)  # type: ignore[attr-defined]
        with TabbedContent(id="tabs"):
            yield ChatTabPane("Session 1", tab_max_length=max_len, show_welcome=True, id="session-1")

    async def _add_log_tab(self) -> None:
        """Open the logs tab, or switch to it if it already exists."""
        tabs = self.query_one("#tabs", TabbedContent)
        existing = tabs.query(f"#{LogTabPane.LOG_TAB_ID}")
        if existing:
            tabs.active = LogTabPane.LOG_TAB_ID
            existing.first().query_one("#log-output").focus()
            return
        max_len = self.app.options.get(Options.TabMaxLength)  # type: ignore[attr-defined]
        pane = LogTabPane(tab_max_length=max_len)
        await tabs.add_pane(pane)
        tabs.active = LogTabPane.LOG_TAB_ID
        pane.query_one("#log-output").focus()

    async def _add_tab(self, label: str | None = None) -> None:
        """Create a new chat session tab."""
        self._tab_counter += 1
        tab_id = f"session-{self._tab_counter}"
        tab_label = label or f"Session {self._tab_counter}"
        tabs = self.query_one("#tabs", TabbedContent)
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

    def _switch_tab(self, delta: int) -> None:
        """Switch to the tab *delta* positions away (wrapping)."""
        tabs = self.query_one("#tabs", TabbedContent)
        panes = list(tabs.query(TabPane))
        if len(panes) <= 1:
            return
        ids = [p.id for p in panes]
        idx = ids.index(tabs.active)
        new_id = ids[(idx + delta) % len(ids)]
        tabs.active = new_id
        # Focus the new pane's chat input so the old pane's focused widget
        # doesn't cause TabbedContent to revert the switch.
        new_pane = tabs.get_pane(new_id)
        if isinstance(new_pane, ChatTabPane):
            new_pane.query_one(ChatPane).query_one("#chat-input").focus()
        elif isinstance(new_pane, LogTabPane):
            new_pane.query_one("#log-output").focus()

    def action_next_tab(self) -> None:
        self._switch_tab(1)

    def action_prev_tab(self) -> None:
        self._switch_tab(-1)

    def action_refocus_input(self) -> None:
        pane: ChatPane = self.app.active_chat_pane  # type: ignore[attr-defined]
        pane.query_one("#chat-input").focus()

    def action_toggle_last_agent_message(self) -> None:
        pane: ChatPane = self.app.active_chat_pane  # type: ignore[attr-defined]
        harnesses = pane.query(AgentMessageHarness)
        for harness in reversed(harnesses):
            msgs = harness.query(ChatMessage)
            if msgs:
                last_msg = list(msgs)[-1]
                last_msg.toggle_collapse()
                return

    def action_toggle_last_tool_call(self) -> None:
        pane: ChatPane = self.app.active_chat_pane  # type: ignore[attr-defined]
        harnesses = pane.query(AgentMessageHarness)
        for harness in reversed(harnesses):
            tool_list = harness._last_tool_list
            if tool_list is not None:
                tool_list.action_toggle_collapse()
                return

    async def action_cycle_mode(self) -> None:
        pane: ChatPane = self.app.active_chat_pane  # type: ignore[attr-defined]
        cycle = {Mode.IDLE: Mode.LEARN, Mode.LEARN: Mode.REVIEW, Mode.REVIEW: Mode.IDLE}
        await pane._set_mode(cycle[pane.session_mode])
