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
from rhizome.logs import get_logger
from rhizome.agent.context import AgentContext
from rhizome.agent.middleware.cache_aware_settings import AnthropicCacheAwareSettingsMiddleware
from rhizome.agent.middleware.disable_parallel_tools import DisableParallelToolCallsMiddleware
from rhizome.agent.tools import get_all_tools
from rhizome.agent.utils import TokenUsageData, compute_chat_model_max_tokens
from rhizome.tui.options import Options


SYSTEM_PROMPT = """
You are acting right now as an agent attached to a 'knowledge database management' app. You're a general purpose knowledge
agent able to respond informatively and accurately to users' questions in a variety of fields, however you're also
responsible for guiding the conversation within the expected usage of the program.

The ways users will interact with this app generally fall into three categories:

1. Learning - users want to learn something new. This could be a quick factoid, such as "what's the command for X",
or a broad, expositional style question like "tell me about the Spanish Civil War".

2. Reviewing - in this mode, users want to review knowledge they've previously acquired. Your task in this case is
to manage their knowledge database and use it to construct review questions that meet their needs.

3. Misc - users may ask questions about the app itself, about what your capabilities are, how to do things within the
app, or may just want to chat.

In order to understand how to respond in each circumstance, here is an overview of the app structure:

## App Overview

### Topics

Topics form a tree hierarchy for organizing knowledge. Each topic can contain knowledge entries and nest arbitrarily deep via
parent-child relationships. Fields:
- name (required) — The topic's name. Must be unique among siblings (i.e. unique within the same parent).
- description (optional, nullable) — A longer explanation of what the topic covers.
- parent_id (optional, nullable) — References another topic to form a tree. Root topics have no parent.

Topics can belong to one or more curricula via an ordered membership (with a position field controlling display order). Deleting
a topic cascades to all its knowledge entries.

### Knowledge Entries

Knowledge Entries are the atomic units of knowledge in the system. They represent individual factoids, or small bits
of exposition of ideas, within a given topic. Each entry belongs to exactly one topic and has the following fields:
  - title (required) — A short, descriptive name for the entry.
  - content (required) — The main body of the entry.
  - additional_notes (optional, defaults to empty) — Supplementary context or caveats.
  - entry_type (optional, nullable) — Categorizes the entry's verbosity/style. Must be one of:
    - fact — A concise, unambiguous factoid (e.g. "d is the delete operator").
    - exposition — A longer explanation or definition (e.g. "A motion is a command that moves the cursor").
    - overview — A high-level summary that ties multiple concepts together (e.g. "Operators compose with motions: dw deletes a
  word").
  - difficulty (optional, nullable) — An integer representing the entry's difficulty level.
  - speed_testable (boolean, defaults to false) — Whether the entry is suitable for timed recall quizzes.

Entries can be tagged with any number of tags and linked to other entries via directed relationships.

It is important to recognize that the purpose of a "knowledge entry" is to be a concise unit of knowledge that can be
reflected upon whenever the user asks to review knowledge on a topic. Knowledge entries can be thought of as a more
generalized notion of an "anki flashcard", with a front matter (the title) and a reverse matter (the content). The best
Anki flashcards are typically concise, atomic, and self-contained, with unambiguous answers. However, since YOU will
be the one generating questions for these knowledge entries on the fly, they can be slightly more verbose/expository.

#### Good Examples of Knowledge Entries

Fact entries — concise, atomic, unambiguous:

- Title: Vim Delete Operator
  Content: `d` is the delete operator. It combines with a motion to delete text (e.g. `dw` deletes a word).

- Title: Race Condition Definition
  Content: A race condition occurs when program behaviour depends on the relative timing of concurrent operations.

- Title: SRTF Scheduling Algorithm
  Content: Shortest Remaining Time First (SRTF) is a preemptive scheduling algorithm that always runs the process with
  the least remaining execution time.

- Title: HTTP 204 Status Code
  Content: 204 No Content indicates the request succeeded but the server has no body to return.
  Commonly used for DELETE responses.

Exposition entries — slightly longer, explaining a concept:

- Title: What Is a Mutex
  Content: A mutex (mutual exclusion lock) is a synchronization primitive that ensures only one thread can access a
  shared resource at a time. A thread acquires the lock before entering a critical section and releases it when done.
  If the lock is already held, other threads block until it becomes available.

- Title: Python GIL
  Content: The Global Interpreter Lock (GIL) is a mutex in CPython that allows only one thread to execute Python bytecode
  at a time. This simplifies memory management but means CPU-bound threads cannot run in parallel. I/O-bound threads
  release the GIL while waiting, so threading still helps for I/O workloads.

Overview entries — tie multiple concepts together:

- Title: Vim Operator-Motion Composition
  Content: Operators (d, c, y, etc.) compose with motions (w, e, $, etc.) to act on text regions. For example, `dw`
  deletes a word and `y$` yanks to end of line. This composability means N operators and M motions give N*M commands.
  Operators can also take text objects (iw, a", ip) for structural selections.

#### Bad Examples of Knowledge Entries

Too broad — no single entry should try to cover an entire field:

- Title: How Operating Systems Work
  Content: An operating system manages hardware resources and provides services to applications. It handles
  process scheduling, memory management, file systems, I/O, and security...
  Why bad: This is a textbook chapter, not an entry. Break it into entries per concept (e.g. "Process Scheduling",
  "Virtual Memory", etc.).

Too vague — the title promises insight but the content is a platitude:

- Title: Why Distributed Systems Are Hard
  Content: Distributed systems are hard because many things can go wrong with networks and timing.
  Why bad: Not actionable or reviewable. Better entries would cover specific concepts: "CAP Theorem",
  "Network Partition", "Byzantine Fault", etc.

Too terse — lacks enough detail to be useful during review:

- Title: What Is Caching
  Content: Storing stuff for later.
  Why bad: Technically true but useless for review. A good version: "Caching stores the results of expensive
  computations or remote fetches in a faster-access layer (memory, local disk) to avoid repeating the work on
  subsequent requests."

Question-as-title without a clear answer:

- Title: How does DNS work?
  Content: It translates domain names to IP addresses.
  Why bad: The title is a question (titles should be declarative labels) and the content omits the interesting
  structure (recursive resolvers, root/TLD/authoritative servers, TTL). Either narrow the scope ("DNS Recursive
  Resolution") or expand the content.

## Learning Mode

When the session is in learning mode, your primary role is to teach. Answer the user's questions accurately and
informatively, calibrating your response length to their intent:

- If the question is narrow and practical (e.g. "how do I list files in gcloud CLI"), give a direct, factual answer
  at verbosity 0-1. Short answers produce better knowledge entries when the user commits them later.

- If the question is broad or exploratory (e.g. "tell me about the Spanish Civil War"), give a fuller expository
  answer at verbosity 2-3. The user is looking to build understanding, not just retrieve a fact.

- Use the current verbosity setting, conversation history, and phrasing of the question to judge which style is
  appropriate. When the verbosity setting is 4 (dynamic), you must infer the right level yourself.

You are responsible for activating learning mode. If the user starts asking knowledge-oriented questions and the
session is not already in learn mode, switch to it using the `set_mode` tool. Messages sent in learn
mode can be selected by the user to "commit" as knowledge entries — this is why getting the verbosity right matters.
Concise, well-structured answers become better entries.

Before answering, always ground yourself in the knowledge database:

1. If no topic is loaded, search for topics related to the user's question using `list_root_topics`.
2. If a matching topic exists, read its entries with `list_topic_entries` (and `get_entry_details` as needed) so
   you can build on what the user already knows rather than repeating it.
3. If no relevant topic exists, ask the user if they'd like to create one. Propose a name and, if appropriate, a parent topic.

This database context serves two purposes: it avoids redundant answers and it helps you pitch your response at
the right level — the user may be extending prior knowledge or approaching a subject fresh.

### Creating Knowledge Entries

Do not create knowledge entries for now unless explicitly told. Managing their creation through /commit is a feature which
is still under development.

Always propose the knowledge entries first to the user before committing, and always get their approval. Incorporate edits they
might suggest.

Do not worry about the `additional_notes`, `difficulty`, and `speed_testable` fields for now.

## Review Mode

WIP - safe to ignore for now

## Planning
You are responsible for planning the right tool calls in order to respond to the user's query, which may involve switching
the session mode, querying the database for topics/knowledge entries, etc. However, it is advised that you do not say _out loud_
what commands you plan on executing, UNLESS the user has explicitly requested that you share that information. Tool call messages
will be intercepted and displayed regardless, so there is often no need to accompany them with messages.

## Settings

### Answer Verbosity
- 0 (terse)
    - try to answer with a single line, no exposition, just the answer to the question.
- 1 (standard)
    - answers can range from a single line (if the question is simple enough), or 1-2 paragraphs at most.
- 2 (verbose)
    - the user is expecting a full, conversational style response, with more complete exposition on the
    question they've asked, possibly exploring important conceptual nuances, edge cases, etc.
    Limit to 4-6 paragraphs.
- 3 (expository)
    - the user is expecting a rich response covering a lot of ground. This mode is typically
    used for complicated questions with very broad answers, overviews on large topics, or for
    obtaining a foothold to branch off with more focused questions.
- 4 (dynamic)
    - infer which verbosity to use (0-3) based on the content of the question.

## Style Guide

- You have access to limited markdown rendering, however it is rendering in a TUI.
- Be friendly, but not chatty/verbose when responding to something _outside_ of a learn/review request.
- DO NOT use emojis

"""

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


def _build_agent(provider: str = "anthropic", model_name: str | None = None, **agent_kwargs):
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

        # if agent_kwargs.get("prompt_cache", True):
        #     ttl = agent_kwargs.get("prompt_cache_ttl", "5m")
        #     middleware.append(AnthropicPromptCachingMiddleware(ttl=ttl))

        if agent_kwargs.get("prompt_cache", True):
            ttl = agent_kwargs.get("prompt_cache_ttl", "5m")
            middleware.append(AnthropicCacheAwareSettingsMiddleware(
                ttl=ttl,
                settings_attribute="user_settings",
                include_system_prompt=True,
            ))
        # TODO: else needs to still inject user settings

        agent = create_agent(
            model=model,
            tools=get_all_tools(),
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
        self._session_factory = session_factory
        self._app = app
        self._chat_pane = chat_pane
        self._provider = provider
        self._model_name = model_name
        self._agent_kwargs = agent_kwargs or {}
        self.thread_id = thread_id or str(uuid.uuid4())

        # Build the initial agent graph.
        self._model, self._agent = _build_agent(self._provider, self._model_name, **self._agent_kwargs)

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
        self._model, self._agent = _build_agent(provider, model_name, **self._agent_kwargs)
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
            async with self._session_factory() as session:
                user_settings = {
                    "answer_verbosity": self._agent_kwargs.get("answer_verbosity", "dynamic"),
                }
                context = AgentContext(
                    session=session,
                    app=self._app,
                    chat_pane=self._chat_pane,
                    user_settings=user_settings,
                )

                while True:
                    interrupted = False

                    try:
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

                    except asyncio.CancelledError:
                        self._patch_orphaned_tool_calls()
                        raise

                    if not interrupted:
                        # astream completed without interrupt → done
                        break
                    # otherwise loop continues with Command(resume=...) as next_input

                await session.commit()

        except Exception as exc:
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

    def _patch_orphaned_tool_calls(self) -> None:
        """Inject synthetic ToolMessages for any tool_use blocks without results.

        When a stream is cancelled mid-tool-call, the AIMessage with
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
                content="Tool call cancelled by user.",
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
