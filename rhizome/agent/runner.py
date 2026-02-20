"""Invoke the agent with a fresh DB session per call."""

from collections.abc import AsyncIterator

from langchain.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import async_sessionmaker

from rhizome.agent.context import AgentContext
from rhizome.tui.state import ChatEntry

SYSTEM_PROMPT = """\
You are a curriculum learning assistant. You help users explore, create, and \
manage structured knowledge curricula.

Current mode: {mode}
{context_line}\

Use your tools to look up and modify curricula, topics, entries, and tags. \
Be concise and helpful.\
"""


def _build_lc_messages(
    messages: list[ChatEntry],
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
        if m.role == "user":
            lc_messages.append(HumanMessage(content=m.content))
        elif m.role == "system":
            lc_messages.append(SystemMessage(content=m.content))
        else:
            lc_messages.append(AIMessage(content=m.content))
    return lc_messages


async def stream_agent(
    agent,
    session_factory: async_sessionmaker,
    messages: list[ChatEntry],
    *,
    mode: str = "idle",
    curriculum_name: str = "",
    topic_name: str = "",
) -> AsyncIterator[str]:
    """Stream text tokens from the agent, yielding each chunk as a str.

    Opens a fresh async session, streams with ``stream_mode="messages"``,
    and commits when the stream is complete.
    """
    lc_messages = _build_lc_messages(
        messages, mode=mode, curriculum_name=curriculum_name, topic_name=topic_name,
    )

    async with session_factory() as session:
        context = AgentContext(session=session)
        async for token, metadata in agent.astream(
            {"messages": lc_messages},
            context=context,
            stream_mode="messages",
        ):
            # Only yield text from the model node's AIMessageChunks.
            if metadata.get("langgraph_node") != "model":
                continue
            if not isinstance(token, AIMessageChunk):
                continue
            text = token.text
            if text:
                yield text
        await session.commit()
