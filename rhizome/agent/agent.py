"""Agent session: owns the LangChain conversation history and agent graph."""

from collections.abc import AsyncIterator, Callable
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

from rhizome.agent.config import get_api_key, get_model_name
from rhizome.agent.context import AgentContext
from rhizome.agent.middleware.cache_aware_settings import AnthropicCacheAwareSettingsMiddleware
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

CURRENT ANSWER VERBOSITY: 4

## Style Guide

- You have access to limited markdown rendering, however it is rendering in a TUI.
- Be friendly, but not chatty/verbose when responding to something _outside_ of a learn/review request.
- DO NOT use emojis

"""

def _build_agent(provider: str = "anthropic", model_name: str | None = None):
    """Build the model + compiled graph."""
    if provider == "anthropic":
        if model_name is None:
            model_name = get_model_name()

        model = init_chat_model(
            model_name,
            api_key=get_api_key(),
            temperature=0.3,
        )

        agent = create_agent(
            model=model,
            tools=get_all_tools(),
            context_schema=AgentContext,
            middleware=[
               AnthropicPromptCachingMiddleware(ttl='5m') 
            ]
            # middleware=[
            #     AnthropicCacheAwareSettingsMiddleware()
            # ]
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
            provider: str = "anthropic",
            model_name: str | None = None,
            on_token_usage_changed: Callable[[], Any] | None = None,
            on_rebuild_agent: Callable[[str, str], Any] | None = None,
        ):
        self._session_factory = session_factory
        self._app = app
        self._provider = provider
        self._model_name = model_name

        # Build the initial agent graph.
        self._model, self._agent = _build_agent(self._provider, self._model_name)

        # Initialize message history with the system prompt, and set up token usage tracking.
        self._history: list[BaseMessage] = [SystemMessage(SYSTEM_PROMPT)]
        self._token_usage = TokenUsageData()
        self._token_usage.max_tokens = compute_chat_model_max_tokens(self._model)
        self.on_token_usage_changed = on_token_usage_changed
        self.on_rebuild_agent = on_rebuild_agent

    def rebuild_agent(self, provider: str, model_name: str) -> None:
        """Rebuild the agent graph with the given provider and model."""
        old_model = self._model_name or "(default)"
        self._provider = provider
        self._model_name = model_name
        self._model, self._agent = _build_agent(provider, model_name)
        self._token_usage.max_tokens = compute_chat_model_max_tokens(self._model)
        if self.on_rebuild_agent is not None:
            self.on_rebuild_agent(old_model, model_name)

    async def on_options_post_update(self, options: Options) -> None:
        """Called by Options.post_update(); rebuilds agent if provider/model changed."""
        provider = options.get(Options.Agent.Provider)
        model_name = options.get(Options.Agent.Model)

        if provider != self._provider or model_name != self._model_name:
            self.rebuild_agent(provider, model_name)

    def add_human_message(self, text: str) -> None:
        self._history.append(HumanMessage(content=text))

    def add_system_notification(self, text: str) -> None:
        # Remark: certain providers only allow a single SystemPrompt at the beginning of the conversation, so we represent these
        # as human messages with a [System] prefix.
        self._history.append(HumanMessage(content=f"[System] {text}"))

    async def stream(self, *, mode: str = "idle", topic_name: str = "") -> AsyncIterator[tuple[str, Any]]:
        """Stream agent output, internally capturing AIMessages and ToolMessages into history.

        Token usage is tracked automatically: ``total_tokens`` is updated from
        ``usage_metadata`` on message chunks, and ``overhead_tokens`` is computed
        after the stream completes.  The ``on_token_usage_changed`` callback fires
        whenever these values change.

        Yields ``(kind, payload)`` tuples with ``kind`` being ``"messages"`` or ``"updates"``.
        """
        try:
            async with self._session_factory() as session:
                context = AgentContext(session=session, app=self._app)
                async for update in self._agent.astream(
                    {"messages": self._history},
                    context=context,
                    stream_mode=["updates", "messages"],
                ):
                    kind, payload = update
                    if kind == "updates":
                        for node_output in payload.values():
                            for msg in node_output.get("messages", []):
                                if isinstance(msg, BaseMessage):
                                    self._history.append(msg)
                                    self._notify_token_usage()
                    elif kind == "messages":
                        chunk, _metadata = payload

                        if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                            if chunk.usage_metadata.get("total_tokens"):
                                self._token_usage.total_tokens = chunk.usage_metadata["total_tokens"]

                            # Extract cache usage from input_token_details
                            details = chunk.usage_metadata.get("input_token_details", {})
                            cache_read = details.get("cache_read")
                            cache_create = details.get("cache_creation")

                            if not cache_read and not cache_create:
                                # Fallback to response_metadata on full messages
                                resp_meta = getattr(chunk, "response_metadata", {})
                                usage = resp_meta.get("usage", {})

                                cache_read = usage.get("cache_read_input_tokens")
                                cache_create = usage.get("cache_creation_input_tokens")

                            if cache_read or cache_create:
                                self._token_usage.cache_read_tokens = cache_read
                                self._token_usage.cache_creation_tokens = cache_create

                            self._notify_token_usage()

                    yield kind, payload
                await session.commit()
        except:
            # Reraise so that the UI can display the error, but still compute overhead tokens for the messages 
            # that were sent before the error occurred.
            raise
        finally:
            # Compute overhead tokens after the stream completes (or errors).
            self._notify_token_usage()

    def _notify_token_usage(self) -> None:
        self._compute_overhead_tokens()
        if self.on_token_usage_changed is not None:
            self.on_token_usage_changed()

    def _compute_overhead_tokens(self) -> None:
        """Estimate overhead tokens (system prompt + tool messages) and update token usage."""
        system_msgs = [
            m for m in self._history 
            if isinstance(m, SystemMessage) or \
               (isinstance(m, HumanMessage) and m.content.startswith("[System]"))
        ]
        tool_msgs = [m for m in self._history if isinstance(m, ToolMessage)]

        system_overhead = count_tokens_approximately(system_msgs)
        tool_overhead = count_tokens_approximately(tool_msgs)

        self._token_usage.breakdown[TokenUsageData.BreakdownCategory.SYSTEM] = system_overhead
        self._token_usage.breakdown[TokenUsageData.BreakdownCategory.TOOL_MESSAGES] = tool_overhead

    @property
    def model(self):
        return self._model

    @property
    def history(self) -> list[BaseMessage]:
        return self._history

    @property
    def token_usage(self) -> TokenUsageData:
        return self._token_usage
