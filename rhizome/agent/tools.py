"""LangChain @tool wrappers around rhizome.db.operations.

Each tool receives its own DB session via a closure over `session_factory`,
eliminating the need for a shared session lock. Tools needing TUI access
(set_mode, rename_tab) capture `chat_pane` from the closure.
"""

from enum import IntEnum

from langchain.tools import tool
from langgraph.types import interrupt
from sqlalchemy import func, select

from rhizome.db.models import KnowledgeEntry, Topic
from rhizome.db.operations import (
    create_entry,
    create_topic,
    get_entry,
    get_topic,
    list_entries,
)
from rhizome.logs import get_logger
from rhizome.tui.types import Mode

_logger = get_logger("agent.tools")

class ToolVisibility(IntEnum):
    LOW = 0       # Housekeeping tools (set_mode, rename_tab) — only visible at max verbosity
    DEFAULT = 1   # Most tools — visible at normal verbosity
    HIGH = 2      # Important tools — always visible

TOOL_VISIBILITY: dict[str, ToolVisibility] = {}

def tool_visibility(level: ToolVisibility):
    """Decorator that registers a tool's visibility level."""
    def decorator(func):
        name = getattr(func, 'name', None) or func.__name__
        if name not in TOOL_VISIBILITY:
            TOOL_VISIBILITY[name] = level
        elif TOOL_VISIBILITY[name] != level:
            _logger.info(
                f"A new tool closure '{name}' has a different visibility level specified than a previous one. "
                f"Previous: {TOOL_VISIBILITY[name]}, new: {level}."
            )
        return func
    return decorator


class ToolGroups:
    """Named groups of tool names for selective inclusion via build_tools()."""
    DB_TOPICS = ["list_all_topics", "show_topics", "create_new_topic"]
    DB_ENTRIES = ["get_entries", "create_entries"]
    DATABASE = DB_TOPICS + DB_ENTRIES
    APP = ["set_topic", "set_mode", "rename_tab", "ask_user_input"]


def build_tools(session_factory, chat_pane=None, included: list[str] | None = None) -> list:
    """Build all tool functions with session_factory and chat_pane closed over.

    Each tool creates its own session via ``async with session_factory() as session``,
    so no session lock is needed. Tools needing ``chat_pane`` capture it from the closure.
    """

    # -----------------------------------------------------------------------
    # Topics
    # -----------------------------------------------------------------------

    @tool("list_all_topics", description=(
        "List the entire topic tree with entry counts. "
        "Returns a nested, indented view of all topics showing [id], name, "
        "and how many knowledge entries each topic contains."
    ))
    async def list_all_topics_tool() -> str:
        async with session_factory() as session:
            # Fetch all topics and entry counts in two queries
            all_topics = (await session.execute(
                select(Topic).order_by(Topic.id)
            )).scalars().all()

            counts = dict((await session.execute(
                select(KnowledgeEntry.topic_id, func.count())
                .group_by(KnowledgeEntry.topic_id)
            )).all())

        if not all_topics:
            return "No topics found."

        # Build tree structure
        by_parent: dict[int | None, list[Topic]] = {}
        for t in all_topics:
            by_parent.setdefault(t.parent_id, []).append(t)

        lines: list[str] = []
        def walk(parent_id: int | None, depth: int) -> None:
            for t in by_parent.get(parent_id, []):
                count = counts.get(t.id, 0)
                indent = "  " * depth
                lines.append(f"{indent}- [{t.id}] {t.name} ({count} entries)")
                walk(t.id, depth + 1)

        walk(None, 0)
        return "\n".join(lines)

    @tool("show_topics", description=(
        "Show one or more topics' details and list all their knowledge entries by title and ID. "
        "Use get_entries to read the full content of specific entries."
    ))
    async def show_topics_tool(topic_ids: list[int]) -> str:
        results: list[str] = []
        async with session_factory() as session:
            for topic_id in topic_ids:
                topic = await get_topic(session, topic_id)
                if topic is None:
                    results.append(f"Topic {topic_id} not found.")
                    continue
                entries = await list_entries(session, topic_id)

                lines = [f"Topic [{topic.id}]: {topic.name}"]
                if topic.description:
                    lines.append(f"Description: {topic.description}")
                lines.append("")
                if not entries:
                    lines.append("No entries in this topic.")
                else:
                    lines.append(f"{len(entries)} entries:")
                    for e in entries:
                        type_str = f" ({e.entry_type.value})" if e.entry_type else ""
                        lines.append(f"  - [{e.id}] {e.title}{type_str}")
                results.append("\n".join(lines))
        return "\n\n---\n\n".join(results)

    @tool("create_new_topic", description="Create a new topic, optionally under a parent topic.")
    async def create_new_topic_tool(
        name: str,
        parent_id: int | None = None,
        description: str | None = None,
    ) -> str:
        async with session_factory() as session:
            topic = await create_topic(session, name=name, parent_id=parent_id, description=description)
            await session.commit()
        return f"Created topic [{topic.id}] {topic.name}"

    # -----------------------------------------------------------------------
    # Entries
    # -----------------------------------------------------------------------

    @tool("get_entries", description=(
        "Get the full details of one or more knowledge entries by their IDs."
    ))
    async def get_entries_tool(entry_ids: list[int]) -> str:
        results: list[str] = []
        async with session_factory() as session:
            for eid in entry_ids:
                entry = await get_entry(session, eid)
                if entry is None:
                    results.append(f"[{eid}] Not found.")
                    continue
                lines = [
                    f"[{entry.id}] {entry.title}",
                    f"Type: {entry.entry_type.value if entry.entry_type else 'unset'}",
                    f"Content: {entry.content}",
                ]
                if entry.additional_notes:
                    lines.append(f"Notes: {entry.additional_notes}")
                if entry.difficulty is not None:
                    lines.append(f"Difficulty: {entry.difficulty}")
                results.append("\n".join(lines))
        return "\n\n---\n\n".join(results)

    @tool("create_entries", description=(
        "Create one or more knowledge entries. Each entry needs: "
        "topic_id (int), title (str), content (str), and optionally "
        "entry_type ('fact'|'exposition'|'overview')."
    ))
    async def create_entries_tool(entries: list[dict]) -> str:
        from rhizome.db.models import EntryType
        created: list[str] = []
        async with session_factory() as session:
            for e in entries:
                parsed_type = EntryType(e["entry_type"]) if e.get("entry_type") else None
                entry = await create_entry(
                    session,
                    topic_id=e["topic_id"],
                    title=e["title"],
                    content=e["content"],
                    entry_type=parsed_type,
                )
                created.append(f"[{entry.id}] {entry.title}")
            await session.commit()
        return f"Created {len(created)} entries:\n" + "\n".join(f"  - {c}" for c in created)

    # -----------------------------------------------------------------------
    # App commands (mode switching, tab renaming, topic selection)
    # -----------------------------------------------------------------------

    @tool("set_topic", description=(
        "Set the active topic for this chat session. "
        "Updates the status bar and notifies the user. "
        "Use this when the user begins learning about a specific topic."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def set_topic_tool(topic_id: int) -> str:
        if chat_pane is None:
            return "Chat pane not available."
        async with session_factory() as session:
            topic = await get_topic(session, topic_id)
            if topic is None:
                return f"Topic {topic_id} not found."
            # Walk up parents to build the path
            path: list[str] = [topic.name]
            current = topic
            while current.parent_id is not None:
                current = await get_topic(session, current.parent_id)
                if current is None:
                    break
                path.append(current.name)
            path.reverse()
        chat_pane.active_topic = topic
        chat_pane._topic_path = path
        chat_pane.update_status_bar()
        return f"Active topic set to: {topic.name}"

    @tool("set_mode", description="Set the active session mode. Accepted values: 'idle', 'learn', 'review'.")
    @tool_visibility(ToolVisibility.LOW)
    async def set_mode_tool(mode: str) -> str:
        try:
            target = Mode(mode)
        except ValueError:
            return f"Invalid mode '{mode}'. Must be one of: idle, learn, review."
        await chat_pane._set_mode(target, silent=True)
        return f"Mode is now: {chat_pane.session_mode.value}"

    @tool("rename_tab", description="Rename the active chat session tab.")
    @tool_visibility(ToolVisibility.LOW)
    async def rename_tab_tool(name: str) -> str:
        await chat_pane._cmd_rename(name)
        return f"Tab renamed to: {name}"

    # -----------------------------------------------------------------------
    # User input (interrupt-based)
    # -----------------------------------------------------------------------

    @tool("ask_user_input", description=(
        "Present a multiple-choice prompt to the user and wait for their selection. "
        "Use this when you need the user to choose between options before proceeding."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def ask_user_input_tool(message: str, choices: list[str]) -> str:
        result = interrupt({"message": message, "options": choices})
        return f"User selected: {result}"

    all_tools = {
        "list_all_topics": list_all_topics_tool,
        "show_topics": show_topics_tool,
        "create_new_topic": create_new_topic_tool,
        "get_entries": get_entries_tool,
        "create_entries": create_entries_tool,
        "set_topic": set_topic_tool,
        "set_mode": set_mode_tool,
        "rename_tab": rename_tab_tool,
        "ask_user_input": ask_user_input_tool,
    }

    if included is None:
        return list(all_tools.values())

    missing = set(included) - set(all_tools)
    if missing:
        raise ValueError(f"Unknown tool names: {missing}")
    return [all_tools[name] for name in included]
