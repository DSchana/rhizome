"""Invoke the agent with a fresh DB session per call."""

from collections.abc import AsyncIterator
from typing import Any

from langchain.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import async_sessionmaker

from rhizome.agent.context import AgentContext
from rhizome.tui.types import ChatMessageData, Role

SYSTEM_PROMPT = """\
You are a general purpose knowledge agent that's attached to some tooling to manage \
knowledge through a local database. Users will ask you questions about things they're \
interested in learning about, and depending on the verbosity they desire, you should \
answer the question accordingly.

Verbosity Settings
==================
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

Example questions you might receive:

- Can you teach me about the POSIX find command?
    - Inferred verbosity: 2

- Can you give me an overview of the Spanish Civil War?
    - Inferred verbosity: 3

- What's the command to keep my MacBook from sleeping?
    - Inferred verbosity: 0 or 1
    - Answer: `caffeinate`, possibly with some exposition on the options

Current mode: {mode}
Current verbosity: 4

You also have access to a suite of tools to look up and modify curricula, topics, entries, and tags.
For the time being you are just expected to respond to questions and not commit changes to the database
through these tools.
"""

def _build_lc_messages(
    messages: list[ChatMessageData],
    *,
    mode: str,
    curriculum_name: str,
    topic_name: str,
) -> list:
    context_line = ""
    if curriculum_name and topic_name:
        context_line = f"Active curriculum: {curriculum_name}, topic: {topic_name}\n"
    elif curriculum_name:
        context_line = f"Active curriculum: {curriculum_name}\n"

    system = SystemMessage(content=SYSTEM_PROMPT.format(mode=mode, context_line=context_line))
    lc_messages: list = [system]
    for m in messages:
        if m.role == Role.USER:
            lc_messages.append(HumanMessage(content=m.content))
        elif m.role == Role.SYSTEM:
            # Internal "system" messages are app-generated info (not LLM system
            # prompts).  Wrap them as HumanMessages so we don't produce multiple
            # SystemMessages — many LLMs only allow one at the start.
            lc_messages.append(HumanMessage(content=f"[System] {m.content}"))
        else:
            lc_messages.append(AIMessage(content=m.content))
    return lc_messages


async def stream_agent(
    agent,
    session_factory: async_sessionmaker,
    messages: list[ChatMessageData],
    *,
    mode: str = "idle",
    curriculum_name: str = "",
    topic_name: str = "",
) -> AsyncIterator[tuple[str, Any]]:
    """Stream agent output as ``(kind, payload)`` tuples.

    Uses dual ``stream_mode=["updates", "messages"]`` so callers receive both
    text tokens and graph state updates.

    Yields:
        ``("messages", text_str)`` — filtered AIMessageChunk text from the model node.
        ``("updates", chunk_dict)`` — raw graph update dicts, passed through unfiltered.
    """
    lc_messages = _build_lc_messages(
        messages, mode=mode, curriculum_name=curriculum_name, topic_name=topic_name,
    )

    async with session_factory() as session:
        context = AgentContext(session=session)
        async for update in agent.astream(
            {"messages": lc_messages},
            context=context,
            stream_mode=["updates", "messages"],
        ):
            yield update
        await session.commit()
