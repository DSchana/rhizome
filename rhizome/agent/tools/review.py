"""Review-mode tools for the review session state machine.

Each tool creates its own DB session via a closure over ``session_factory``,
matching the pattern in ``tools.py``.  Tools that mutate ReviewState return
``Command(update={"review": ...})``.
"""

from __future__ import annotations

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command
from rhizome.agent.state import ReviewConfig, ReviewScope, ReviewState
from rhizome.agent.tools.visibility import ToolVisibility, tool_visibility
from rhizome.db.operations import (
    add_review_interaction,
    complete_review_session,
    create_review_session,
    get_flashcard_entry_ids,
    get_interaction_stats,
    get_sessions_by_topics,
    update_session_ephemeral,
    update_session_instructions,
    update_session_plan,
    update_session_summary,
)
from rhizome.db.models import KnowledgeEntry
from rhizome.logs import get_logger

from sqlalchemy import select

_logger = get_logger("agent.review_tools")


def build_review_tools(session_factory) -> list:
    """Build all review-mode tool functions with session_factory closed over."""

    # -------------------------------------------------------------------
    # SCOPING Phase
    # -------------------------------------------------------------------

    @tool_visibility(ToolVisibility.LOW)
    @tool("get_review_sessions", description=(
        "Get past review sessions overlapping the given topic IDs. "
        "Returns session date, scope summary, and final_summary text. "
        "Excludes ephemeral sessions. Ranked by topic overlap (IoU), limited to 5."
    ))
    async def get_review_sessions_tool(topic_ids: list[int]) -> str:
        async with session_factory() as session:
            sessions = await get_sessions_by_topics(session, topic_ids)

        if not sessions:
            return "No prior review sessions found for these topics."

        lines: list[str] = []
        for rs in sessions:
            parts = [f"Session #{rs.id}"]
            parts.append(f"Date: {rs.created_at.strftime('%Y-%m-%d %H:%M')}")
            if rs.completed_at:
                parts.append("Status: completed")
            else:
                parts.append("Status: incomplete")
            if rs.final_summary:
                parts.append(f"Summary:\n{rs.final_summary}")
            else:
                parts.append("Summary: (none)")
            lines.append("\n".join(parts))

        return "\n\n---\n\n".join(lines)

    @tool_visibility(ToolVisibility.LOW)
    @tool("set_review_scope", description=(
        "Lock in the review scope from a list of entry IDs. "
        "Derives topic IDs from the entries automatically. "
        "Creates the ReviewSession DB record and initializes ReviewState. "
        "Advances phase to CONFIGURING."
    ))
    async def set_review_scope_tool(entry_ids: list[int], runtime: ToolRuntime) -> Command:
        # Derive topic_ids from entries
        async with session_factory() as session:
            result = await session.execute(
                select(KnowledgeEntry.topic_id)
                .where(KnowledgeEntry.id.in_(entry_ids))
                .distinct()
            )
            topic_ids = list(result.scalars().all())

            # Create the ReviewSession DB record
            review_session = await create_review_session(
                session, topic_ids=topic_ids, entry_ids=entry_ids,
            )
            await session.commit()
            session_id = review_session.id

        new_state: ReviewState = {
            "phase": "configuring",
            "session_id": session_id,
            "scope": ReviewScope(topic_ids=topic_ids, entry_ids=list(entry_ids)),
            "config": None,
            "flashcard_queue": [],
            "entry_coverage": {eid: 0 for eid in entry_ids},
            "interaction_count": 0,
            "discussion_plan": None,
        }

        msg = f"Scope set: {len(entry_ids)} entries across {len(topic_ids)} topics. Phase: CONFIGURING."
        return Command(update={
            "review": new_state,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    # -------------------------------------------------------------------
    # CONFIGURING Phase
    # -------------------------------------------------------------------

    @tool_visibility(ToolVisibility.LOW)
    @tool("configure_review", description=(
        "Set review session configuration. Advances phase to PLANNING. "
        "Parameters: style ('flashcard'|'conversation'|'mixed'), "
        "critique_timing ('during'|'after'), question_source ('existing'|'generated'|'both'), "
        "ephemeral (bool), user_instructions (optional str)."
    ))
    async def configure_review_tool(
        style: str,
        critique_timing: str,
        question_source: str,
        ephemeral: bool,
        runtime: ToolRuntime,
        user_instructions: str | None = None,
    ) -> Command:
        review_state: ReviewState = runtime.state["review"]
        session_id = review_state["session_id"]

        async with session_factory() as session:
            if ephemeral:
                await update_session_ephemeral(session, session_id, True)
            if user_instructions:
                await update_session_instructions(session, session_id, user_instructions)
            await session.commit()

        config = ReviewConfig(
            style=style,
            critique_timing=critique_timing,
            question_source=question_source,
            ephemeral=ephemeral,
            user_instructions=user_instructions,
        )

        new_state = dict(review_state)
        new_state["config"] = config
        new_state["phase"] = "planning"

        parts = [
            f"Style: {style}",
            f"Timing: {critique_timing}",
            f"Source: {question_source}",
            f"Ephemeral: {ephemeral}",
        ]
        if user_instructions:
            parts.append(f"Instructions: {user_instructions}")
        msg = "Configuration set. " + ", ".join(parts) + ". Phase: PLANNING."

        return Command(update={
            "review": new_state,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    # -------------------------------------------------------------------
    # PLANNING Phase
    # -------------------------------------------------------------------

    @tool_visibility(ToolVisibility.LOW)
    @tool("set_review_flashcards", description=(
        "Set the flashcard queue to the given list of flashcard IDs. "
        "Replaces the current queue entirely — use this to add, remove, "
        "reorder, or clear flashcards."
    ))
    async def set_review_flashcards_tool(
        flashcard_ids: list[int],
        runtime: ToolRuntime,
    ) -> Command:
        review_state: ReviewState = runtime.state["review"]
        new_state = dict(review_state)
        new_state["flashcard_queue"] = list(flashcard_ids)

        msg = f"Flashcard queue set: {len(flashcard_ids)} card(s)."
        return Command(update={
            "review": new_state,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    @tool_visibility(ToolVisibility.LOW)
    @tool("add_flashcards_to_review", description=(
        "Append flashcard IDs to the review queue. Use this after "
        "accept_flashcard_proposal or with existing flashcard IDs from "
        "list_flashcards."
    ))
    async def add_flashcards_to_review_tool(
        flashcard_ids: list[int],
        runtime: ToolRuntime,
    ) -> Command:
        review_state: ReviewState = runtime.state["review"]
        new_state = dict(review_state)
        new_queue = list(review_state["flashcard_queue"]) + list(flashcard_ids)
        new_state["flashcard_queue"] = new_queue

        msg = f"Added {len(flashcard_ids)} flashcard(s) to queue. Queue size: {len(new_queue)}."
        return Command(update={
            "review": new_state,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    @tool_visibility(ToolVisibility.LOW)
    @tool("start_review", description=(
        "Store the discussion plan and advance to the REVIEWING phase. "
        "Call this after planning is complete."
    ))
    async def start_review_tool(
        runtime: ToolRuntime,
        plan: str | None = None,
    ) -> Command:
        review_state: ReviewState = runtime.state["review"]
        session_id = review_state["session_id"]

        if plan:
            async with session_factory() as session:
                await update_session_plan(session, session_id, plan)
                await session.commit()

        new_state = dict(review_state)
        new_state["phase"] = "reviewing"
        new_state["discussion_plan"] = plan

        msg = "Review started. Plan saved." if plan else "Review started."
        return Command(update={
            "review": new_state,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    # -------------------------------------------------------------------
    # REVIEWING Phase
    # -------------------------------------------------------------------

    @tool_visibility(ToolVisibility.LOW)
    @tool("record_review_interaction", description=(
        "Record a Q&A interaction during the review. Exactly one of flashcard_id "
        "or entry_ids must be provided. Extracts question/answer text from message "
        "history using message IDs. Updates entry coverage and interaction count."
    ))
    async def record_review_interaction_tool(
        question_message_id: int,
        answer_message_id: int,
        score: int,
        runtime: ToolRuntime,
        feedback: str | None = None,
        flashcard_id: int | None = None,
        entry_ids: list[int] | None = None,
    ) -> Command:
        if (flashcard_id is None) == (entry_ids is None):
            return Command(update={
                "messages": [ToolMessage(
                    content="Error: exactly one of flashcard_id or entry_ids must be provided.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        review_state: ReviewState = runtime.state["review"]
        messages = runtime.state["messages"]

        # Extract question and answer text from message history
        question_text = None
        user_response = None
        for msg in messages:
            msg_id = (msg.additional_kwargs or {}).get("rhizome", {}).get("message_id")
            if msg_id == question_message_id:
                question_text = msg.content if isinstance(msg.content, str) else str(msg.content)
            elif msg_id == answer_message_id:
                user_response = msg.content if isinstance(msg.content, str) else str(msg.content)

        if question_text is None:
            return Command(update={
                "messages": [ToolMessage(
                    content=f"Error: message with ID {question_message_id!r} not found.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })
        if user_response is None:
            return Command(update={
                "messages": [ToolMessage(
                    content=f"Error: message with ID {answer_message_id!r} not found.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        # Resolve entry_ids from flashcard if needed
        resolved_entry_ids: list[int]
        if flashcard_id is not None:
            async with session_factory() as session:
                resolved_entry_ids = await get_flashcard_entry_ids(session, flashcard_id)
        else:
            resolved_entry_ids = list(entry_ids)  # type: ignore[arg-type]

        session_id = review_state["session_id"]
        interaction_count = review_state["interaction_count"]
        position = interaction_count + 1

        # Write ReviewInteraction + ReviewInteractionEntry DB records
        async with session_factory() as session:
            await add_review_interaction(
                session,
                session_id=session_id,
                question_text=question_text,
                user_response=user_response,
                entry_ids=resolved_entry_ids,
                feedback=feedback,
                score=score,
                position=position,
                flashcard_id=flashcard_id,
            )
            await session.commit()

        # Update ReviewState
        new_state = dict(review_state)
        new_coverage = dict(review_state["entry_coverage"])
        for eid in resolved_entry_ids:
            new_coverage[eid] = new_coverage.get(eid, 0) + 1
        new_state["entry_coverage"] = new_coverage
        new_state["interaction_count"] = position

        # Pop flashcard from queue if applicable
        if flashcard_id is not None:
            new_queue = list(review_state["flashcard_queue"])
            if flashcard_id in new_queue:
                new_queue.remove(flashcard_id)
            new_state["flashcard_queue"] = new_queue

        # Build tool message
        total_entries = len(new_coverage)
        touched = sum(1 for c in new_coverage.values() if c > 0)
        untouched_ids = [eid for eid, c in new_coverage.items() if c == 0]

        queue_total = len(review_state["flashcard_queue"])
        queue_remaining = len(new_state.get("flashcard_queue", []))

        parts = [f"Recorded #{position} (score: {score}/5)."]
        if queue_total > 0:
            parts.append(f"Flashcard queue: {queue_remaining}/{queue_total}.")
        parts.append(f"Coverage: {touched}/{total_entries} entries touched.")

        if untouched_ids:
            parts.append(f"Untouched: {untouched_ids}.")
        else:
            parts.append("All entries covered at least once.")

        msg = " ".join(parts)
        return Command(update={
            "review": new_state,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    # -------------------------------------------------------------------
    # SUMMARIZING Phase
    # -------------------------------------------------------------------

    @tool_visibility(ToolVisibility.DEFAULT)
    @tool("complete_review_session", description=(
        "Compute aggregate stats from review interactions and advance to SUMMARIZING. "
        "Returns stats for the agent to use when writing the final_summary."
    ))
    async def complete_review_session_tool(runtime: ToolRuntime) -> Command:
        review_state: ReviewState = runtime.state["review"]
        session_id = review_state["session_id"]

        async with session_factory() as session:
            stats = await get_interaction_stats(session, session_id)
            await complete_review_session(session, session_id)
            await session.commit()

        new_state = dict(review_state)
        new_state["phase"] = "summarizing"

        # Format stats for the agent
        lines = [
            f"Total interactions: {stats['total']}",
            f"Scored interactions: {stats['scored']}",
            f"Average score: {stats['average_score']}/5" if stats['average_score'] is not None else "Average score: N/A",
        ]

        if stats["per_entry"]:
            lines.append("\nPer-entry breakdown:")
            for eid, entry_stats in sorted(stats["per_entry"].items()):
                avg = round(entry_stats["total_score"] / entry_stats["scored"], 2) if entry_stats["scored"] > 0 else "N/A"
                lines.append(f"  Entry [{eid}]: {entry_stats['count']} interactions, avg score: {avg}")

        msg = "\n".join(lines)
        return Command(update={
            "review": new_state,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    @tool_visibility(ToolVisibility.DEFAULT)
    @tool("save_review_summary", description=(
        "Write the final_summary to the ReviewSession DB record, "
        "set completed_at, and clear ReviewState. Call this after the agent "
        "has composed the summary."
    ))
    async def save_review_summary_tool(
        final_summary: str,
        runtime: ToolRuntime,
    ) -> Command:
        review_state: ReviewState = runtime.state["review"]
        session_id = review_state["session_id"]

        async with session_factory() as session:
            await update_session_summary(session, session_id, final_summary)
            await session.commit()

        msg = "Summary saved. Review session complete."
        return Command(update={
            "review": None,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    # -------------------------------------------------------------------
    # General Purpose
    # -------------------------------------------------------------------

    @tool("inspect_review_state", description=(
        "Dump the current ReviewState as a readable summary. "
        "Shows phase, session ID, scope, config, queue size, coverage, and interaction count."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def inspect_review_state_tool(runtime: ToolRuntime) -> str:
        review_state: ReviewState | None = runtime.state.get("review")
        if review_state is None:
            return "No active review session."

        total_entries = len(review_state["entry_coverage"])
        touched = sum(1 for c in review_state["entry_coverage"].values() if c > 0)

        lines = [
            f"Phase: {review_state['phase']}",
            f"Session ID: {review_state['session_id']}",
        ]

        scope = review_state.get("scope")
        if scope:
            lines.append(f"Scope: {len(scope['entry_ids'])} entries across {len(scope['topic_ids'])} topics")

        config = review_state.get("config")
        if config:
            lines.append(f"Config: style={config['style']}, timing={config['critique_timing']}, source={config['question_source']}, ephemeral={config['ephemeral']}")

        lines.append(f"Flashcard queue: {len(review_state['flashcard_queue'])} remaining")
        lines.append(f"Coverage: {touched}/{total_entries} entries touched")
        lines.append(f"Interactions: {review_state['interaction_count']}")

        if review_state.get("discussion_plan"):
            lines.append(f"Plan: (set)")

        return "\n".join(lines)

    @tool_visibility(ToolVisibility.LOW)
    @tool("clear_review_state", description=(
        "Abandon the current review session and clear ReviewState. "
        "Does NOT delete DB records — the session remains as-is."
    ))
    async def clear_review_state_tool(runtime: ToolRuntime) -> Command:
        msg = "Review state cleared."
        return Command(update={
            "review": None,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    return {
        "get_review_sessions": get_review_sessions_tool,
        "set_review_scope": set_review_scope_tool,
        "configure_review": configure_review_tool,
        "set_review_flashcards": set_review_flashcards_tool,
        "add_flashcards_to_review": add_flashcards_to_review_tool,
        "start_review": start_review_tool,
        "record_review_interaction": record_review_interaction_tool,
        "complete_review_session": complete_review_session_tool,
        "save_review_summary": save_review_summary_tool,
        "inspect_review_state": inspect_review_state_tool,
        "clear_review_state": clear_review_state_tool,
    }
