"""AgentMessageHarness — encapsulates one agent turn's display lifecycle."""

from __future__ import annotations

from typing import Any

from textual.message import Message
from textual.widget import Widget
from textual.widgets.markdown import Markdown, MarkdownStream

from langchain.messages import AIMessageChunk, ToolMessage

from rhizome.agent.tools import TOOL_VISIBILITY, ToolVisibility
from rhizome.tui.types import Mode, Role
from rhizome.tui.widgets.interrupt_choices import InterruptChoices
from rhizome.tui.widgets.message import ChatMessage, MarkdownChatMessage
from rhizome.tui.widgets.thinking import ThinkingIndicator
from rhizome.tui.widgets.tool_call_list import ToolCallList


class AgentMessageHarness(Widget):
    """Manages ThinkingIndicator → interleaved ChatMessage/ToolCallList segments for one agent turn."""

    _VISIBILITY_MAP: dict[str, ToolVisibility] = {
        "debug": ToolVisibility.LOW,
        "default": ToolVisibility.DEFAULT,
        "essential_only": ToolVisibility.HIGH,
    }

    DEFAULT_CSS = """
    AgentMessageHarness {
        height: auto;
        layout: vertical;
    }
    """

    def __init__(self, tool_use_visibility: str = "default", **kwargs) -> None:
        super().__init__(**kwargs)
        self._display_threshold = self._VISIBILITY_MAP.get(
            tool_use_visibility, ToolVisibility.DEFAULT
        )
        self._thinking: ThinkingIndicator | None = None
        self._segments: list[ChatMessage | ToolCallList | InterruptChoices] = []
        self._active_stream: MarkdownStream | None = None
        self._interrupt_widget: InterruptChoices | None = None
        self._finalized: bool = False

    @property
    def _session_mode(self) -> Mode:
        # Needed to avoid circular import
        from rhizome.tui.widgets.chat_pane import ChatPane

        pane = self.query_ancestor(ChatPane)
        return pane.session_mode

    @property
    def chat_message_body(self) -> str | None:
        """Concatenated body text from all ChatMessage segments."""
        bodies = [seg._body for seg in self._segments if isinstance(seg, ChatMessage)]
        return "".join(bodies) if bodies else None

    @property
    def is_thinking(self) -> bool:
        return self._thinking is not None

    def on_mount(self) -> None:
        self.set_interval(0.2, self._sync_session_mode)

    def _sync_session_mode(self) -> None:
        # Only respond to changes in the session mode _before_ we've finalized
        # the message. This way, changes to the mode won't change the background
        # colour of past messages.
        if not self._finalized:
            mode = self._session_mode
            self.set_class(mode == Mode.LEARN, "learn-mode")
            self.set_class(mode == Mode.REVIEW, "review-mode")
            self.set_class(mode == Mode.IDLE, "idle-mode")

            # Apply mode classes to the current (last) ToolCallList only;
            # prior ToolCallList segments keep the mode they were created with.
            last_tl = self._last_tool_list
            if last_tl is not None:
                last_tl.set_class(mode == Mode.LEARN, "learn-mode")
                last_tl.set_class(mode == Mode.REVIEW, "review-mode")
                last_tl.set_class(mode == Mode.IDLE, "idle-mode")

    @property
    def _last_tool_list(self) -> ToolCallList | None:
        """Return the last ToolCallList segment, or None."""
        for seg in reversed(self._segments):
            if isinstance(seg, ToolCallList):
                return seg
        return None

    async def start_thinking(self) -> None:
        """Mount a ThinkingIndicator inside this harness."""
        # Remove shortcut hints from all previous messages in the message area
        parent = self.parent
        if parent is not None:
            for msg in parent.query("ChatMessage.--show-shortcut"):
                msg.remove_class("--show-shortcut")
                msg._update_collapse_label()
            for tl in parent.query("ToolCallList.--show-hint"):
                tl.remove_class("--show-hint")
                tl._update_title()
        self._thinking = ThinkingIndicator()
        await self.mount(self._thinking)

    async def stop_thinking(self) -> None:
        """Idempotently remove the ThinkingIndicator."""
        if self._thinking is not None:
            await self._thinking.remove()
            self._thinking = None

    async def append(self, token: AIMessageChunk) -> None:
        """Append a text token to the streaming message.

        Creates a new ChatMessage segment if the last segment is not a ChatMessage
        (or if no segments exist yet).
        """
        if self._finalized:
            raise Exception  # TODO: raise a proper exception

        # Agents will produce AIMessageChunks of type "input_json_delta" when constructing
        # args for tool calls, which have empty text. We want to ignore these until the
        # agent produces an actual text token as part of it's message, so we don't initialize
        # the chat message too early.
        if not token.text:
            return

        # If the last segment isn't a ChatMessage, start a new one.
        if not self._segments or not isinstance(self._segments[-1], ChatMessage):
            await self._start_chat_segment()

        chat = self._segments[-1]
        assert isinstance(chat, ChatMessage)

        chat._body += token.text
        if not chat._collapsed and self._active_stream:
            await self._active_stream.write(token.text)

    async def _start_chat_segment(self) -> None:
        """Create and mount a new ChatMessage segment, opening a fresh stream."""
        chat = MarkdownChatMessage(role=Role.AGENT, mode=self._session_mode)
        self._segments.append(chat)
        await self.mount(chat)
        self._active_stream = Markdown.get_stream(chat.inner_markdown)

    async def post_update(self, chunk: dict) -> None:
        """Handle a graph state update. Extracts tool call names from AIMessage content."""
        for update in chunk.values():
            for msg in update.get("messages", []):
                content = getattr(msg, "content", None)
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name")
                        if name:
                            level = TOOL_VISIBILITY.get(name, ToolVisibility.DEFAULT)
                            if level < self._display_threshold:
                                continue
                            # If the last segment isn't a ToolCallList, close the
                            # active stream and start a new tool list segment.
                            if not self._segments or not isinstance(self._segments[-1], ToolCallList):
                                await self._close_active_stream()
                                tool_list = ToolCallList(classes=f"{self._session_mode.value}-mode")
                                self._segments.append(tool_list)
                                await self.mount(tool_list)
                            last = self._segments[-1]
                            assert isinstance(last, ToolCallList)
                            last.add_tool(name)

    async def _close_active_stream(self) -> None:
        """Stop the active MarkdownStream if one is open."""
        if self._active_stream is not None:
            await self._active_stream.stop()
            self._active_stream = None

    # ------------------------------------------------------------------
    # Textual messages for interrupt coordination
    # ------------------------------------------------------------------

    class InterruptPending(Message):
        """Posted when an interrupt widget is mounted and needs user input."""

        def __init__(self, widget: InterruptChoices) -> None:
            super().__init__()
            self.widget = widget

    class InterruptResolved(Message):
        """Posted when the user has resolved an interrupt."""

    # ------------------------------------------------------------------
    # Callback methods for AgentSession.stream()
    # ------------------------------------------------------------------

    async def on_message(self, kind: str, payload: Any) -> None:
        """Callback for ``"messages"`` chunks from the agent stream."""
        chunk, _metadata = payload
        if isinstance(chunk, ToolMessage):
            return
        await self.append(chunk)

    async def on_update(self, kind: str, payload: Any) -> None:
        """Callback for ``"updates"`` chunks from the agent stream."""
        await self.post_update(payload)

    async def on_interrupt(self, interrupt_value: Any) -> Any:
        """Callback for graph interrupts. Blocks until the user responds.

        Mounts an ``InterruptChoices`` widget, posts ``InterruptPending`` so
        ``ChatPane`` can disable its input, and awaits the user's selection.
        """
        await self.stop_thinking()
        await self._close_active_stream()

        # Build options from the interrupt value
        if isinstance(interrupt_value, dict):
            prompt = interrupt_value.get("message", "The agent requires your input:")
            options = interrupt_value.get("options", ["Continue", "Cancel"])
        else:
            prompt = str(interrupt_value) if interrupt_value else "The agent requires your input:"
            options = ["Continue", "Cancel"]

        self._interrupt_widget = InterruptChoices(prompt=prompt, options=options)
        self._segments.append(self._interrupt_widget)
        await self.mount(self._interrupt_widget)

        # Tell ChatPane to disable its input and focus the choices widget
        self.post_message(self.InterruptPending(widget=self._interrupt_widget))

        try:
            result = await self._interrupt_widget.wait_for_selection()
        finally:
            self._interrupt_widget = None
            # Tell ChatPane to re-enable input
            self.post_message(self.InterruptResolved())
            await self.start_thinking()

        return result

    async def finalize(self) -> str:
        """Stop the stream and finalize the message. Returns accumulated message body."""
        # Remark: The (no response) message is posted if no ChatMessage segments exist,
        # meaning the agent never said anything.
        return await self._finalize(empty_chat_message="(no response)")

    async def cancel(self) -> str:
        """Cancel the current turn. Returns accumulated body (may be empty)."""
        # Clean up any pending interrupt widget
        if self._interrupt_widget is not None:
            self._interrupt_widget.cancel()
            self._interrupt_widget = None
        return await self._finalize(empty_chat_message="*(cancelled)*")

    async def _finalize(self, empty_chat_message: str | None = None) -> str:
        # Remove the thinking indicator if present
        await self.stop_thinking()

        # Close the stream if opened
        await self._close_active_stream()

        has_chat = any(isinstance(seg, ChatMessage) for seg in self._segments)

        if not has_chat:
            if empty_chat_message:
                chat = MarkdownChatMessage(role=Role.AGENT, content=empty_chat_message)
                self._segments.append(chat)
                await self.mount(chat)
            else:
                self._finalized = True
                return ""

        self._finalized = True
        # Notify each ChatMessage segment so it can update collapsibility.
        for seg in self._segments:
            if isinstance(seg, ChatMessage):
                seg.update_body(seg._body)
        # Show shortcut hint on the last ChatMessage segment (only if collapsible)
        chat_segments = [seg for seg in self._segments if isinstance(seg, ChatMessage)]
        if chat_segments and chat_segments[-1].has_class("--collapsible"):
            chat_segments[-1].add_class("--show-shortcut")
            chat_segments[-1]._update_collapse_label()
        # Show hint on the last ToolCallList segment
        tool_segments = [seg for seg in self._segments if isinstance(seg, ToolCallList)]
        if tool_segments:
            tool_segments[-1].add_class("--show-hint")
            tool_segments[-1]._update_title()
        # Join bodies from all ChatMessage segments
        return "".join(
            seg._body for seg in self._segments if isinstance(seg, ChatMessage)
        )
