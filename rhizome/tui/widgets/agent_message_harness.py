"""AgentMessageHarness — encapsulates one agent turn's display lifecycle."""

from __future__ import annotations

from textual.widget import Widget
from textual.widgets.markdown import Markdown, MarkdownStream

from rhizome.tui.types import Mode, Role
from rhizome.tui.widgets.message import ChatMessage
from rhizome.tui.widgets.thinking import ThinkingIndicator


class AgentMessageHarness(Widget):
    """Manages ThinkingIndicator → ChatMessage + Markdown stream for one agent turn."""

    DEFAULT_CSS = """
    AgentMessageHarness {
        height: auto;
        layout: vertical;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._thinking: ThinkingIndicator | None = None
        self._chat_message: ChatMessage | None = None
        self._stream: MarkdownStream | None = None

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

    async def start_thinking(self) -> None:
        """Mount a ThinkingIndicator inside this harness."""
        self._thinking = ThinkingIndicator()
        await self.mount(self._thinking)

    async def stop_thinking(self) -> None:
        """Idempotently remove the ThinkingIndicator."""
        if self._thinking is not None:
            await self._thinking.remove()
            self._thinking = None

    async def append(self, token: str) -> None:
        """Append a text token to the streaming message.

        On the first call, replaces the ThinkingIndicator with a ChatMessage
        and starts a Markdown stream.
        """
        # First, initialize the chat message if we haven't already.
        if self._chat_message is None:
            await self._init_chat_message()

            assert self._chat_message is not None
            assert self._stream is not None

        self._chat_message._body += token
        if not self._chat_message._collapsed:
            if self._stream:
                await self._stream.write(token)

    async def _init_chat_message(self) -> None:
        """Initialize the ChatMessage widget and exposes the stream.

        self._chat_message and self._stream are guaranteed to be set after
        calling this coroutine.
        """
        # Remove the thinking indicator if present
        await self.stop_thinking()

        if self._chat_message is not None and self._stream is not None:
            return

        self._chat_message = ChatMessage(role=Role.AGENT, mode=self._session_mode)
        await self.mount(self._chat_message)
        
        # Grab a handle to the stream, for writing tokens
        self._stream = Markdown.get_stream(self._chat_message.inner_markdown)

    async def post_update(self, update: dict) -> None:
        """Handle a graph state update. No-op for now.

        TODO: render tool-call status widgets here in the future.
        """

    async def finalize(self) -> str:
        """Stop the stream and finalize the message. Returns accumulated message body."""
        # Remove the thinking indicator if present
        await self.stop_thinking()

        # Close the stream if opened
        if self._stream is not None:
            await self._stream.stop()

        if self._chat_message is None:
            # Post a simple "(no response)" message.
            # Remark: finalize() gets called after the agent "successfully" finishes writing
            # it's message (and wasn't interrupted by the user or an error). Getting to this point
            # with an empty _chat_message means _init_chat_message was never called, meaning
            # the agent yielded no token output at all.
            self._chat_message = ChatMessage(role=Role.AGENT, content="(no response)")
            await self.mount(self._chat_message)
        
        return self._chat_message._body

    async def cancel(self) -> str:
        """Cancel the current turn. Returns accumulated body (may be empty)."""
        # Remove the thinking indicator if present
        await self.stop_thinking()

        # Close the stream if opened
        if self._stream is not None:
            await self._stream.stop()

        if self._chat_message is None:

            self._chat_message = ChatMessage(role=Role.AGENT, content="*(cancelled)*")
            await self.mount(self._chat_message)

        return self._chat_message._body
