"""Agent session: owns the LangChain conversation history and agent graph."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from rhizome.agent.config import get_api_key, get_model_name
from rhizome.agent.system_prompt import SYSTEM_PROMPT
from rhizome.logs import get_logger
from rhizome.agent.context import AgentContext
from rhizome.agent.middleware.disable_parallel_tools import DisableParallelToolCallsMiddleware
from rhizome.agent.middleware.inject_user_settings import InjectUserSettingsMiddleware
from rhizome.agent.middleware.penultimate_cache import AnthropicPenultimateCacheMiddleware
from rhizome.agent.tools import build_tools
from rhizome.agent.utils import TokenUsageData, compute_chat_model_max_tokens
from rhizome.tui.options import Options


def get_agent_kwargs(options: Options) -> dict[str, Any]:
    """Build provider-specific kwargs from the current options."""
    provider = options.get(Options.Agent.Provider)
    kwargs: dict[str, Any] = {}
    kwargs["parallel_tool_calling"] = options.get(Options.Agent.ParallelToolCalling) == "enabled"
    kwargs["temperature"] = options.get(Options.Agent.Temperature)
    kwargs["answer_verbosity"] = options.get(Options.Agent.AnswerVerbosity)
    if provider == "anthropic":
        kwargs["prompt_cache"] = options.get(Options.Agent.Anthropic.PromptCache) == "enabled"
        kwargs["prompt_cache_ttl"] = options.get(Options.Agent.Anthropic.PromptCacheTTL)
    return kwargs


_logger = get_logger("agent")


def _build_agent(tools: list, provider: str = "anthropic", model_name: str | None = None, **agent_kwargs):
    """Build the model + compiled graph."""
    _logger.info("Building agent (provider=%s, model=%s)", provider, model_name)
    if provider == "anthropic":
        if model_name is None:
            model_name = get_model_name()

        temperature = agent_kwargs.get("temperature", 0.3)
        model = init_chat_model(
            model_name,
            api_key=get_api_key(),
            temperature=temperature,
        )

        middleware = []

        if not agent_kwargs.get("parallel_tool_calling", True):
            middleware.append(DisableParallelToolCallsMiddleware())

        middleware.append(InjectUserSettingsMiddleware(
            settings_attribute="user_settings",
            include_system_prompt=True,
        ))

        if agent_kwargs.get("prompt_cache", True):
            ttl = agent_kwargs.get("prompt_cache_ttl", "5m")
            middleware.append(AnthropicPenultimateCacheMiddleware(ttl=ttl))

        agent = create_agent(
            model=model,
            tools=tools,
            context_schema=AgentContext,
            middleware=middleware,
            checkpointer=InMemorySaver(),
        )
        return model, agent
    else:
        raise ValueError(f"Unsupported provider: {provider}")


class AgentSession:
    """Encapsulates a single conversation's agent graph and message history."""

    def __init__(
            self,
            session_factory,
            *,
            app=None,
            chat_pane=None,
            provider: str = "anthropic",
            model_name: str | None = None,
            agent_kwargs: dict[str, Any] | None = None,
            on_token_usage_changed: Callable[[], Any] | None = None,
            on_rebuild_agent: Callable[[str, str], Any] | None = None,
            thread_id: str | None = None,
        ):
        self._provider = provider
        self._model_name = model_name
        self._agent_kwargs = agent_kwargs or {}
        self.thread_id = thread_id or str(uuid.uuid4())

        # Build tools (closed over session_factory and chat_pane) and the initial agent graph.
        self._tools = build_tools(session_factory, chat_pane=chat_pane)
        self._model, self._agent = _build_agent(self._tools, self._provider, self._model_name, **self._agent_kwargs)

        # Initialize message history with the system prompt, and set up token usage tracking.
        self._session_logger = get_logger("agent.session")
        self._session_logger.info("Session created (provider=%s, model=%s)", provider, model_name)

        self._history: list[BaseMessage] = [SystemMessage(SYSTEM_PROMPT)]
        self._token_usage = TokenUsageData()
        self._token_usage.max_tokens = compute_chat_model_max_tokens(self._model)
        self.on_token_usage_changed = on_token_usage_changed
        self.on_rebuild_agent = on_rebuild_agent

    def rebuild_agent(self, provider: str, model_name: str, agent_kwargs: dict[str, Any] | None = None) -> None:
        """Rebuild the agent graph with the given provider and model."""
        old_model = self._model_name or "(default)"
        self._session_logger.info("Agent rebuilt: %s → %s", old_model, model_name)
        self._provider = provider
        self._model_name = model_name
        if agent_kwargs is not None:
            self._agent_kwargs = agent_kwargs
        self._model, self._agent = _build_agent(self._tools, provider, model_name, **self._agent_kwargs)
        self._token_usage.max_tokens = compute_chat_model_max_tokens(self._model)
        if self.on_rebuild_agent is not None:
            self.on_rebuild_agent(old_model, model_name)

    async def on_options_post_update(self, options: Options) -> None:
        """Called by Options.post_update(); rebuilds agent if provider/model/kwargs changed."""
        provider = options.get(Options.Agent.Provider)
        model_name = options.get(Options.Agent.Model)
        new_kwargs = get_agent_kwargs(options)

        if provider != self._provider or model_name != self._model_name or new_kwargs != self._agent_kwargs:
            self.rebuild_agent(provider, model_name, agent_kwargs=new_kwargs)

    def add_human_message(self, text: str) -> None:
        self._history.append(HumanMessage(content=text))

    def add_system_notification(self, text: str) -> None:
        # Remark: certain providers only allow a single SystemPrompt at the beginning of the conversation, so we represent these
        # as human messages with a [System] prefix.
        self._history.append(HumanMessage(content=f"[System] {text}"))

    async def stream(
        self,
        *,
        mode: str = "idle",
        topic_name: str = "",
        on_message: Callable[[str, Any], Awaitable[None]] | None = None,
        on_update: Callable[[str, Any], Awaitable[None]] | None = None,
        on_interrupt: Callable[[Any], Awaitable[Any]] | None = None,
        post_chunk_handler: Callable[[], Any] | None = None,
    ) -> None:
        """Stream agent output using callbacks, with interrupt/resume support.

        Token usage is tracked automatically: ``total_tokens`` is updated from
        ``usage_metadata`` on message chunks, and ``overhead_tokens`` is computed
        after the stream completes.  The ``on_token_usage_changed`` callback fires
        whenever these values change.

        Callbacks:
            on_message(kind, payload) — called for each ``"messages"`` chunk
            on_update(kind, payload) — called for each ``"updates"`` chunk
            on_interrupt(interrupt_value) — called when the graph interrupts;
                must return the resume value to continue the graph
            post_chunk_handler() — called after every chunk (e.g. for scrolling)
        """
        self._session_logger.debug("Stream started (mode=%s, topic=%s)", mode, topic_name)
        config = {"configurable": {"thread_id": self.thread_id}}
        next_input: dict | Command = {"messages": self._history}

        try:
            user_settings = {
                "answer_verbosity": self._agent_kwargs.get("answer_verbosity", "auto"),
            }
            context = AgentContext(user_settings=user_settings)

            while True:
                interrupted = False

                async for update in self._agent.astream(
                    next_input,
                    config=config,
                    context=context,
                    stream_mode=["updates", "messages"],
                ):
                    kind, payload = update

                    if kind == "updates":

                        # First, inspect the payload for any completed messages and
                        # append them to the internal message history.
                        for node_output in payload.values():

                            # Remark: when an interrupt occurs, that registers as a node_output consisting
                            # of a tuple (Interrupt,). I don't think there's anything we need to do
                            # with that though?
                            if not isinstance(node_output, dict):
                                continue

                            for msg in node_output.get("messages", []):
                                if not isinstance(msg, BaseMessage):
                                    continue
                                self._history.append(msg)

                                # Notify token usage to recompute token breakdowns into
                                # system/tool tokens.
                                self._notify_token_usage()

                        # Check for interrupt
                        if (
                            on_interrupt and \
                            "__interrupt__" in payload and \
                            payload["__interrupt__"]
                        ):
                            interrupt_value = payload["__interrupt__"]

                            # Extract the value from the interrupt info
                            if isinstance(interrupt_value, (list, tuple)) and len(interrupt_value) > 0:
                                interrupt_value = interrupt_value[0]
                            value = getattr(interrupt_value, "value", interrupt_value)

                            # Pass to interrupt handler
                            resume = await on_interrupt(value)

                            # Construct the Command break, restarting the stream with
                            # Command(resume) as the next input.
                            if isinstance(resume, Command):
                                next_input = resume
                            else:
                                next_input = Command(resume=resume)
                            interrupted = True
                            break

                        # Pass to update handler
                        if on_update:
                            await on_update(kind, payload)

                    elif kind == "messages":
                        chunk, _metadata = payload

                        # Extract token/cache usage metadata and notify a
                        # token usage update.
                        self._extract_usage_metadata(chunk)

                        # Pass to message handler
                        if on_message:
                            await on_message(kind, payload)

                    if post_chunk_handler:
                        result = post_chunk_handler()
                        if result is not None and hasattr(result, "__await__"):
                            await result

                if not interrupted:
                    # astream completed without interrupt → done
                    break
                # otherwise loop continues with Command(resume=...) as next_input

        except asyncio.CancelledError:
            self._patch_orphaned_tool_calls("Tool call cancelled by user.")
            raise
        except Exception as exc:
            self._patch_orphaned_tool_calls(
                f"An error has occurred during the stream request: {type(exc).__name__}"
            )
            self._session_logger.error("Stream error: %s", exc)
            raise
        else:
            self._session_logger.debug(
                f"Stream complete (tokens={self._token_usage.total_tokens}, "
                f"cache_read={self._token_usage.cache_read_tokens}, "
                f"cache_create={self._token_usage.cache_creation_tokens})"
            )
        finally:
            self._notify_token_usage()

    def _extract_usage_metadata(self, chunk):
        if not (hasattr(chunk, "usage_metadata") and chunk.usage_metadata):
            return
        
        if chunk.usage_metadata.get("total_tokens"):
            self._token_usage.total_tokens = chunk.usage_metadata["total_tokens"]

        details = chunk.usage_metadata.get("input_token_details", {})
        cache_read = details.get("cache_read")
        cache_create = details.get("cache_creation")

        if not cache_read and not cache_create:
            resp_meta = getattr(chunk, "response_metadata", {})
            usage = resp_meta.get("usage", {})
            cache_read = usage.get("cache_read_input_tokens")
            cache_create = usage.get("cache_creation_input_tokens")

        if cache_read or cache_create:
            self._token_usage.cache_read_tokens = cache_read
            self._token_usage.cache_creation_tokens = cache_create

        self._notify_token_usage()

    def _patch_orphaned_tool_calls(self, message: str) -> None:
        """Inject synthetic ToolMessages for any tool_use blocks without results.

        When a stream is interrupted mid-tool-call, the AIMessage with
        ``tool_use`` content may already be in the history but the
        corresponding ``ToolMessage`` was never appended.  The Anthropic
        API rejects conversations where a ``tool_use`` has no matching
        ``tool_result``, so we scan backwards and patch the gap.
        """
        # Collect tool_call IDs that already have a ToolMessage.
        answered: set[str] = set()
        for msg in self._history:
            if isinstance(msg, ToolMessage) and msg.tool_call_id:
                answered.add(msg.tool_call_id)

        # Walk backwards to find the most recent AIMessage with tool calls.
        # In normal operation this is the last (or second-to-last) message.
        orphaned_ids: list[str] = []
        for msg in reversed(self._history):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc["id"] not in answered:
                        orphaned_ids.append(tc["id"])
                break  # only patch the most recent AIMessage

        if not orphaned_ids:
            return

        self._session_logger.info(
            "Patching %d orphaned tool call(s): %s",
            len(orphaned_ids), orphaned_ids,
        )
        for tc_id in orphaned_ids:
            self._history.append(ToolMessage(
                content=message,
                tool_call_id=tc_id,
            ))

    def _notify_token_usage(self) -> None:
        self._compute_overhead_tokens()
        if self.on_token_usage_changed is not None:
            self.on_token_usage_changed()

    def _compute_overhead_tokens(self) -> None:
        """Estimate overhead tokens (system prompt + tool messages) and update token usage."""
        system_msgs = [m for m in self._history if self._is_system_message(m)]
        tool_msgs = [m for m in self._history if self._is_tool_message(m)]

        system_overhead = count_tokens_approximately(system_msgs)
        tool_overhead = count_tokens_approximately(tool_msgs)

        self._token_usage.breakdown[TokenUsageData.BreakdownCategory.SYSTEM] = system_overhead
        self._token_usage.breakdown[TokenUsageData.BreakdownCategory.TOOL_MESSAGES] = tool_overhead

    def _is_system_message(self, msg) -> bool:
        if isinstance(msg, SystemMessage):
            return True
        
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str):
                if content.startswith("[System]"):
                    return True
            elif isinstance(content, (list, tuple)):
                if len(content) != 1:
                    # TODO: might need to refactor the way we grab system messages for token counts
                    # to account for this?
                    return False 
                content = content[0]
                if isinstance(content, str) and content.startswith("[System]"):
                    return True
                if (
                    isinstance(content, dict) and
                    content.get("type") == "text" and
                    content.get("text", "").startswith("[System]")
                ):
                    return True
            
        return False

    def _is_tool_message(self, msg) -> bool:
        return isinstance(msg, ToolMessage)

    @property
    def model(self):
        return self._model

    @property
    def history(self) -> list[BaseMessage]:
        return self._history

    @property
    def token_usage(self) -> TokenUsageData:
        return self._token_usage
