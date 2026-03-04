"""LangChain @tool wrappers around rhizome.db.operations.

Each tool receives its own DB session via a closure over `session_factory`,
eliminating the need for a shared session lock. Tools needing TUI access
(set_mode, rename_tab) capture `chat_pane` from the closure.
"""

from enum import IntEnum

from langchain.tools import tool
from langgraph.types import interrupt

from rhizome.db.operations import (
    create_entry,
    create_topic,
    get_entries_by_tag,
    get_entry,
    get_subtree,
    list_children,
    list_curricula,
    list_entries,
    list_root_topics,
    list_tags,
    list_topics_in_curriculum,
    search_entries,
    tag_entry,
)


class ToolVisibility(IntEnum):
    LOW = 0       # Housekeeping tools (set_mode, rename_tab) — only visible at max verbosity
    DEFAULT = 1   # Most tools — visible at normal verbosity
    HIGH = 2      # Important tools — always visible

TOOL_VISIBILITY: dict[str, ToolVisibility] = {}


def tool_visibility(level: ToolVisibility):
    """Decorator that registers a tool's visibility level."""
    def decorator(func):
        name = getattr(func, 'name', None) or func.__name__
        TOOL_VISIBILITY[name] = level
        return func
    return decorator


class ToolGroups:
    """Named groups of tool names for selective inclusion via build_tools()."""
    DB_CURRICULA = ["list_all_curricula", "list_curriculum_topics"]
    DB_TOPICS = ["list_root_topics", "list_topic_children", "get_topic_subtree", "create_new_topic"]
    DB_ENTRIES = ["search_knowledge_entries", "list_topic_entries", "get_entry_details", "create_knowledge_entry"]
    DB_TAGS = ["list_all_tags", "get_entries_by_tag_name", "tag_knowledge_entry"]
    DATABASE = DB_TOPICS + DB_ENTRIES + DB_TAGS
    APP = ["set_mode", "rename_tab", "ask_user_input"]


def build_tools(session_factory, chat_pane=None, included: list[str] | None = None) -> list:
    """Build all tool functions with session_factory and chat_pane closed over.

    Each tool creates its own session via ``async with session_factory() as session``,
    so no session lock is needed. Tools needing ``chat_pane`` capture it from the closure.
    """

    # -----------------------------------------------------------------------
    # Curricula
    # -----------------------------------------------------------------------

    @tool("list_all_curricula", description="List every curriculum in the database.")
    async def list_all_curricula_tool() -> str:
        async with session_factory() as session:
            curricula = await list_curricula(session)
        if not curricula:
            return "No curricula found."
        return "\n".join(
            f"- [{c.id}] {c.name}" + (f": {c.description}" if c.description else "")
            for c in curricula
        )

    @tool("list_curriculum_topics", description="List the topics belonging to a curriculum, in order.")
    async def list_curriculum_topics_tool(curriculum_id: int) -> str:
        async with session_factory() as session:
            topics = await list_topics_in_curriculum(session, curriculum_id)
        if not topics:
            return "No topics in this curriculum."
        return "\n".join(f"- [{t.id}] {t.name}" for t in topics)

    # -----------------------------------------------------------------------
    # Topics
    # -----------------------------------------------------------------------

    @tool("list_root_topics", description="List all top-level (root) topics.")
    async def list_root_topics_tool() -> str:
        async with session_factory() as session:
            topics = await list_root_topics(session)
        if not topics:
            return "No root topics found."
        return "\n".join(f"- [{t.id}] {t.name}" for t in topics)

    @tool("list_topic_children", description="List direct children of a topic.")
    async def list_topic_children_tool(parent_id: int) -> str:
        async with session_factory() as session:
            children = await list_children(session, parent_id)
        if not children:
            return "No children found for this topic."
        return "\n".join(f"- [{t.id}] {t.name}" for t in children)

    @tool("get_topic_subtree", description="Get the full subtree under a topic (all descendants).")
    async def get_topic_subtree_tool(root_topic_id: int) -> str:
        async with session_factory() as session:
            nodes = await get_subtree(session, root_topic_id)
        if not nodes:
            return "No descendants found."
        return "\n".join(
            f"{'  ' * node['depth']}- [{node['topic'].id}] {node['topic'].name}"
            for node in nodes
        )

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

    @tool("search_knowledge_entries", description="Search knowledge entries by keyword in title or content.")
    async def search_knowledge_entries_tool(
        query: str,
        topic_id: int | None = None,
        curriculum_id: int | None = None,
    ) -> str:
        async with session_factory() as session:
            entries = await search_entries(session, query, topic_id=topic_id, curriculum_id=curriculum_id)
        if not entries:
            return "No entries matched the search."
        return "\n".join(f"- [{e.id}] {e.title}" for e in entries)

    @tool("list_topic_entries", description="List all knowledge entries for a given topic.")
    async def list_topic_entries_tool(topic_id: int) -> str:
        async with session_factory() as session:
            entries = await list_entries(session, topic_id)
        if not entries:
            return "No entries for this topic."
        return "\n".join(f"- [{e.id}] {e.title}" for e in entries)

    @tool("get_entry_details", description="Get the full details of a knowledge entry by its ID.")
    async def get_entry_details_tool(entry_id: int) -> str:
        async with session_factory() as session:
            entry = await get_entry(session, entry_id)
        if entry is None:
            return f"Entry {entry_id} not found."
        lines = [
            f"Title: {entry.title}",
            f"Type: {entry.entry_type}",
            f"Content: {entry.content}",
        ]
        if entry.additional_notes:
            lines.append(f"Notes: {entry.additional_notes}")
        if entry.difficulty is not None:
            lines.append(f"Difficulty: {entry.difficulty}")
        return "\n".join(lines)

    @tool("create_knowledge_entry", description="Create a new knowledge entry under a topic.")
    async def create_knowledge_entry_tool(
        topic_id: int,
        title: str,
        content: str,
        entry_type: str | None = None,
    ) -> str:
        from rhizome.db.models import EntryType
        parsed_type = EntryType(entry_type) if entry_type is not None else None
        async with session_factory() as session:
            entry = await create_entry(
                session, topic_id=topic_id, title=title, content=content, entry_type=parsed_type,
            )
            await session.commit()
        return f"Created entry [{entry.id}] {entry.title}"

    # -----------------------------------------------------------------------
    # Tags
    # -----------------------------------------------------------------------

    @tool("list_all_tags", description="List every tag in the database.")
    async def list_all_tags_tool() -> str:
        async with session_factory() as session:
            tags = await list_tags(session)
        if not tags:
            return "No tags found."
        return "\n".join(f"- [{t.id}] {t.name}" for t in tags)

    @tool("get_entries_by_tag_name", description="Get all knowledge entries with a given tag.")
    async def get_entries_by_tag_name_tool(tag_name: str) -> str:
        async with session_factory() as session:
            entries = await get_entries_by_tag(session, tag_name)
        if not entries:
            return f"No entries tagged '{tag_name}'."
        return "\n".join(f"- [{e.id}] {e.title}" for e in entries)

    @tool("tag_knowledge_entry", description="Add a tag to a knowledge entry. Creates the tag if needed.")
    async def tag_knowledge_entry_tool(entry_id: int, tag_name: str) -> str:
        async with session_factory() as session:
            await tag_entry(session, entry_id=entry_id, tag_name=tag_name)
            await session.commit()
        return f"Tagged entry {entry_id} with '{tag_name}'."

    # -----------------------------------------------------------------------
    # App commands (mode switching, tab renaming)
    # -----------------------------------------------------------------------

    @tool("set_mode", description="Set the active session mode. Accepted values: 'idle', 'learn', 'review'.")
    @tool_visibility(ToolVisibility.LOW)
    async def set_mode_tool(mode: str) -> str:
        from rhizome.tui.types import Mode
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
        "list_all_curricula": list_all_curricula_tool,
        "list_curriculum_topics": list_curriculum_topics_tool,
        "list_root_topics": list_root_topics_tool,
        "list_topic_children": list_topic_children_tool,
        "get_topic_subtree": get_topic_subtree_tool,
        "create_new_topic": create_new_topic_tool,
        "search_knowledge_entries": search_knowledge_entries_tool,
        "list_topic_entries": list_topic_entries_tool,
        "get_entry_details": get_entry_details_tool,
        "create_knowledge_entry": create_knowledge_entry_tool,
        "list_all_tags": list_all_tags_tool,
        "get_entries_by_tag_name": get_entries_by_tag_name_tool,
        "tag_knowledge_entry": tag_knowledge_entry_tool,
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
