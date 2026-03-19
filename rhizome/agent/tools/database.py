"""Database tools — topic and entry CRUD for the agent."""

from langchain.tools import tool
from langgraph.types import interrupt
from sqlalchemy import func, select

from rhizome.db.models import KnowledgeEntry, Topic
from rhizome.db.operations import (
    create_entry,
    create_topic,
    delete_topic,
    get_entry,
    get_subtree,
    get_topic,
    list_entries,
)


def build_database_tools(session_factory) -> dict:
    """Build topic and entry tools with session_factory closed over."""

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

    @tool("delete_topics", description=(
        "Delete one or more topics by ID. This is irreversible — all knowledge "
        "entries under each topic will also be deleted. Subtrees (child topics) "
        "are deleted bottom-up automatically. Requires user approval."
    ))
    async def delete_topics_tool(topic_ids: list[int]) -> str:
        # Gather info for the warning message
        topic_names: list[str] = []
        async with session_factory() as session:
            for tid in topic_ids:
                topic = await get_topic(session, tid)
                if topic is None:
                    return f"Topic {tid} not found."
                subtree = await get_subtree(session, tid)
                entry_count = (await session.execute(
                    select(func.count()).where(KnowledgeEntry.topic_id == tid)
                )).scalar() or 0
                child_count = len(subtree)
                parts = [f"[{tid}] {topic.name}"]
                if child_count:
                    parts.append(f"{child_count} subtopic(s)")
                if entry_count:
                    parts.append(f"{entry_count} entry/entries")
                topic_names.append(", ".join(parts))

        summary = "; ".join(topic_names)
        result = interrupt({
            "type": "warning",
            "message": (
                f"WARNING: the agent has requested to delete topic(s): "
                f"{summary}. This action is irreversible and will cascade to "
                f"all entries and subtopics."
            ),
        })

        if result != "Approve":
            return f"User denied deletion: {result}"

        # Perform deletion — subtrees must be deleted bottom-up
        deleted: list[str] = []
        async with session_factory() as session:
            for tid in topic_ids:
                topic = await get_topic(session, tid)
                if topic is None:
                    deleted.append(f"[{tid}] not found (skipped)")
                    continue
                # Delete subtree bottom-up (deepest first)
                subtree = await get_subtree(session, tid)
                for node in reversed(subtree):
                    await delete_topic(session, node["topic"].id)
                # Delete the root topic itself
                name = topic.name
                await delete_topic(session, tid)
                deleted.append(f"[{tid}] {name}")
            await session.commit()
        return f"Deleted {len(deleted)} topic(s):\n" + "\n".join(f"  - {d}" for d in deleted)

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

    return {
        "list_all_topics": list_all_topics_tool,
        "show_topics": show_topics_tool,
        "create_new_topic": create_new_topic_tool,
        "delete_topics": delete_topics_tool,
        "get_entries": get_entries_tool,
        "create_entries": create_entries_tool,
    }
