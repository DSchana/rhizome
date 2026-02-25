"""AgentMessageHarness — encapsulates one agent turn's display lifecycle."""

from __future__ import annotations

from textual.widget import Widget
from textual.widgets.markdown import Markdown, MarkdownStream

from rhizome.tui.colors import Colors
from rhizome.tui.types import Mode, Role
from rhizome.tui.widgets.message import ChatMessage
from rhizome.tui.widgets.thinking import ThinkingIndicator
from rhizome.tui.widgets.tool_call_list import ToolCallList

from langchain.messages import AIMessageChunk


class AgentMessageHarness(Widget):
    """Manages ThinkingIndicator → ChatMessage + Markdown stream for one agent turn."""

    DEFAULT_CSS = f"""
    AgentMessageHarness {{
        height: auto;
        layout: vertical;
    }}
    AgentMessageHarness.idle-mode {{
        background: {Colors.IDLE_AGENT_BG};
    }}
    AgentMessageHarness.learn-mode {{
        background: {Colors.LEARN_AGENT_BG};
    }}
    AgentMessageHarness.review-mode {{
        background: {Colors.REVIEW_AGENT_BG};
    }}
    AgentMessageHarness.idle-mode ToolCallList {{
        background: {Colors.IDLE_TOOLCALL_BG};
        border: solid {Colors.IDLE_TOOLCALL_BORDER};
    }}
    AgentMessageHarness.learn-mode ToolCallList {{
        background: {Colors.LEARN_TOOLCALL_BG};
        border: solid {Colors.LEARN_TOOLCALL_BORDER};
    }}
    AgentMessageHarness.review-mode ToolCallList {{
        background: {Colors.REVIEW_TOOLCALL_BG};
        border: solid {Colors.REVIEW_TOOLCALL_BORDER};
    }}
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._thinking: ThinkingIndicator | None = None
        self._tool_list: ToolCallList | None = None
        self._chat_message: ChatMessage | None = None
        self._stream: MarkdownStream | None = None
        self._finalized: bool = False

    @property
    def _session_mode(self) -> Mode:
        pane = self.app.active_chat_pane  # type: ignore[attr-defined]
        return pane.session_mode
    
    @property
    def chat_message(self) -> ChatMessage | None:
        return self._chat_message
    
    @property
    def chat_message_body(self) -> str | None:
        return None if self._chat_message is None else self._chat_message._body
    
    @property
    def agent_message_started(self) -> bool:
        return self._chat_message is not None and self._stream is not None
    
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
            self.set_class(self._session_mode == Mode.LEARN, "learn-mode")
            self.set_class(self._session_mode == Mode.REVIEW, "review-mode")
            self.set_class(self._session_mode == Mode.IDLE, "idle-mode")

    async def start_thinking(self) -> None:
        """Mount a ThinkingIndicator inside this harness."""
        self._thinking = ThinkingIndicator()
        await self.mount(self._thinking)

    async def stop_thinking(self) -> None:
        """Idempotently remove the ThinkingIndicator."""
        if self._thinking is not None:
            await self._thinking.remove()
            self._thinking = None

    async def append(self, token: AIMessageChunk) -> None:
        """Append a text token to the streaming message.

        On the first call, replaces the ThinkingIndicator with a ChatMessage
        and starts a Markdown stream.
        """
        if self._finalized:
            raise Exception # TODO: raise a proper exception
        
        # Agents will produce AIMessageChunks of type "input_json_delta" when constructing
        # args for tool calls, which have empty text. We want to ignore these until the
        # agent produces an actual text token as part of it's message, so we don't initialize
        # the chat message too early.
        if not token.text:
            return
        
        # First, initialize the chat message if we haven't already.
        if self._chat_message is None:
            await self._init_chat_message()

            assert self._chat_message is not None
            assert self._stream is not None

        self._chat_message._body += token.text
        if not self._chat_message._collapsed:
            if self._stream:
                await self._stream.write(token.text)

    async def _init_chat_message(self) -> None:
        """Initialize the ChatMessage widget and exposes the stream.

        self._chat_message and self._stream are guaranteed to be set after
        calling this coroutine.
        """
        if self._chat_message is not None and self._stream is not None:
            return

        self._chat_message = ChatMessage(role=Role.AGENT, mode=self._session_mode)
        await self.mount(self._chat_message)
        
        # Grab a handle to the stream, for writing tokens
        self._stream = Markdown.get_stream(self._chat_message.inner_markdown)

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
                            if self._tool_list is None:
                                self._tool_list = ToolCallList()
                                await self.mount(self._tool_list)
                            self._tool_list.add_tool(name)

    async def finalize(self) -> str:
        """Stop the stream and finalize the message. Returns accumulated message body."""
        # Remark: The (no response) message is posted if the chat message widget was never
        # initialized, meaning the agent never said anything.
        return await self._finalize(empty_chat_message="(no response)")

    async def cancel(self) -> str:
        """Cancel the current turn. Returns accumulated body (may be empty)."""
        return await self._finalize(empty_chat_message="*(cancelled)*")

    async def _finalize(self, empty_chat_message: str | None = None) -> str:
        # Remove the thinking indicator if present
        await self.stop_thinking()

        # Close the stream if opened
        if self._stream is not None:
            await self._stream.stop()

        if self._chat_message is None:
            if empty_chat_message:
                self._chat_message = ChatMessage(role=Role.AGENT, content=empty_chat_message)
                await self.mount(self._chat_message)
            else:
                return ""

        # Flag that we're finished, so that we
        self._finalized = True
        return self._chat_message._body