"""Review-mode tools for the review session state machine.

Each tool creates its own DB session via a closure over ``session_factory``,
matching the pattern in ``tools.py``.  Tools that mutate ReviewState return
``Command(update={"review": ...})``.
"""

from __future__ import annotations

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command, interrupt
from rhizome.agent.state import ReviewConfig, ReviewScope, ReviewState
from rhizome.agent.tools.visibility import ToolVisibility, tool_visibility
from rhizome.db.operations import (
    add_review_interaction,
    complete_review_session,
    create_review_session,
    get_flashcard_entry_ids,
    get_flashcards_by_ids,
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

# Match the constant in FlashcardReview to avoid cross-layer import.
AUTO_SCORE = -1


def build_review_tools(session_factory, scorer=None) -> dict:
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
        "Record a conversational Q&A interaction during the review. "
        "For flashcard-based interactions use present_flashcards / score_flashcards instead. "
        "Extracts question/answer text from message history using message IDs. "
        "Updates entry coverage and interaction count."
    ))
    async def record_review_interaction_tool(
        question_message_id: int,
        answer_message_id: int,
        score: int,
        entry_ids: list[int],
        runtime: ToolRuntime,
        feedback: str | None = None,
    ) -> Command:
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
                entry_ids=list(entry_ids),
                feedback=feedback,
                score=score,
                position=position,
            )
            await session.commit()

        # Update ReviewState
        new_state = dict(review_state)
        new_coverage = dict(review_state["entry_coverage"])
        for eid in entry_ids:
            new_coverage[eid] = new_coverage.get(eid, 0) + 1
        new_state["entry_coverage"] = new_coverage
        new_state["interaction_count"] = position

        # Build tool message
        total_entries = len(new_coverage)
        touched = sum(1 for c in new_coverage.values() if c > 0)
        untouched_ids = [eid for eid, c in new_coverage.items() if c == 0]

        parts = [f"Recorded #{position} (score: {score}/5)."]
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

    @tool_visibility(ToolVisibility.LOW)
    @tool("present_flashcards", description=(
        "Present flashcards to the user via the FlashcardReview widget. "
        "By default pops from the queue: one card for critique-during, all "
        "cards for critique-after. Pass flashcard_ids to override. "
        "Self-scored and again cards are handled automatically; "
        "'auto' cards are scored by an internal subagent."
    ))
    async def present_flashcards_tool(
        runtime: ToolRuntime,
        flashcard_ids: list[int] | None = None,
    ) -> Command:
        review_state: ReviewState = runtime.state["review"]
        queue = list(review_state["flashcard_queue"])

        # Determine which flashcards to present
        if flashcard_ids is not None:
            ids_to_present = list(flashcard_ids)
        else:
            if not queue:
                return Command(update={
                    "messages": [ToolMessage(
                        content="Error: flashcard queue is empty and no flashcard_ids provided.",
                        tool_call_id=runtime.tool_call_id,
                    )],
                })
            # Pop one card for critique-during, all cards for critique-after
            config = review_state.get("config")
            critique_timing = config["critique_timing"] if config else "after"
            if critique_timing == "during":
                ids_to_present = [queue[0]]
            else:
                ids_to_present = list(queue)

        # Fetch flashcard data from DB
        async with session_factory() as session:
            flashcards = await get_flashcards_by_ids(session, ids_to_present)

        if not flashcards:
            return Command(update={
                "messages": [ToolMessage(
                    content="Error: no flashcards found for the given IDs.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        flashcard_map = {fc.id: fc for fc in flashcards}

        # Build card data for the widget
        card_data = [
            {"id": fc.id, "question": fc.question_text, "answer": fc.answer_text}
            for fc in flashcards
        ]

        # Call interrupt to present the widget
        is_single = len(card_data) == 1
        result = interrupt({
            "type": "flashcard_review",
            "cards": card_data,
            "auto_score": True,
            "user_input_enabled": True,
            "show_complete_status": not is_single,
        })

        # Process results
        new_state = dict(review_state)
        new_queue = list(review_state["flashcard_queue"])
        new_coverage = dict(review_state["entry_coverage"])
        interaction_count = review_state["interaction_count"]
        session_id = review_state["session_id"]

        again_ids: list[int] = []
        auto_cards: list[dict] = []  # {"id", "question", "answer", "user_answer", "entry_ids"}
        scored_count = 0
        user_answers: dict[int, str] = {}  # fc_id -> user_answer for summary

        for card_result in result["cards"]:
            fc_id = card_result["id"]
            fc = flashcard_map.get(fc_id)
            if fc is None:
                continue

            entry_ids = [fe.entry_id for fe in fc.flashcard_entries]
            score = card_result["score"]
            user_answer = card_result.get("user_answer", "")
            user_answers[fc_id] = user_answer

            # Remove from queue regardless of score
            if fc_id in new_queue:
                new_queue.remove(fc_id)

            if score == 0:
                # "again" — requeue at end
                again_ids.append(fc_id)
            elif score == AUTO_SCORE:
                # Auto — will be scored by subagent below
                auto_cards.append({
                    "id": fc_id,
                    "question": fc.question_text,
                    "answer": fc.answer_text,
                    "user_answer": user_answer,
                    "testing_notes": fc.testing_notes,
                    "entry_ids": entry_ids,
                    "duration": card_result.get("duration"),
                })
            elif score is not None:
                # Self-scored — record interaction immediately
                interaction_count += 1
                async with session_factory() as session:
                    await add_review_interaction(
                        session,
                        session_id=session_id,
                        question_text=fc.question_text,
                        user_response=user_answer,
                        entry_ids=entry_ids,
                        score=score,
                        position=interaction_count,
                        flashcard_id=fc_id,
                    )
                    await session.commit()
                for eid in entry_ids:
                    new_coverage[eid] = new_coverage.get(eid, 0) + 1
                scored_count += 1

        # Score auto cards via subagent
        auto_scored: list[dict] = []  # [{"id", "score", "feedback"}]
        if auto_cards and scorer is not None:
            scorer_input = "Score the following flashcard answers:\n\n" + "\n---\n".join(
                f"Flashcard {ac['id']}:\n"
                f"  Question: {ac['question']}\n"
                f"  Expected answer: {ac['answer']}\n"
                f"  User's answer: {ac['user_answer'] or '(blank)'}\n"
                f"  Time spent: {ac['duration']}s\n"
                + (f"  Testing notes: {ac['testing_notes']}\n" if ac.get("testing_notes") else "")
                for ac in auto_cards
            )

            _logger.debug("Invoking scorer subagent with %d card(s)", len(auto_cards))
            _, _, _ = await scorer.ainvoke(scorer_input)

            if scorer.structured_response is not None:
                scores_by_id = {
                    r.flashcard_id: r for r in scorer.structured_response.results
                }
                auto_card_map = {ac["id"]: ac for ac in auto_cards}

                for fc_id, ac in auto_card_map.items():
                    scorer_result = scores_by_id.get(fc_id)
                    if scorer_result is None:
                        _logger.warning("Scorer did not return result for flashcard %d", fc_id)
                        continue

                    auto_score = scorer_result.score
                    feedback = scorer_result.feedback

                    if auto_score == 0:
                        again_ids.append(fc_id)
                    else:
                        interaction_count += 1
                        async with session_factory() as session:
                            await add_review_interaction(
                                session,
                                session_id=session_id,
                                question_text=ac["question"],
                                user_response=ac["user_answer"],
                                entry_ids=ac["entry_ids"],
                                feedback=feedback,
                                score=auto_score,
                                position=interaction_count,
                                flashcard_id=fc_id,
                            )
                            await session.commit()
                        for eid in ac["entry_ids"]:
                            new_coverage[eid] = new_coverage.get(eid, 0) + 1

                    auto_scored.append({
                        "id": fc_id,
                        "score": auto_score,
                        "feedback": feedback,
                    })
            else:
                _logger.warning("Scorer subagent failed to produce structured output")

        # Requeue "again" cards at end
        new_queue.extend(again_ids)

        new_state["flashcard_queue"] = new_queue
        new_state["entry_coverage"] = new_coverage
        new_state["interaction_count"] = interaction_count

        # Build summary message
        parts = []
        completed = result.get("completed", False)
        if completed:
            parts.append(f"Flashcard session complete.")
        else:
            parts.append(f"Flashcard session cancelled.")

        if user_answers:
            parts.append("\nUser answers:")
            for fc_id, answer in user_answers.items():
                fc = flashcard_map.get(fc_id)
                q = fc.question_text if fc else "?"
                parts.append(f"  - Flashcard {fc_id} (Q: {q}): {answer or '(blank)'}")
        if scored_count:
            parts.append(f"{scored_count} card(s) self-scored and recorded.")
        if auto_scored:
            parts.append(f"{len(auto_scored)} card(s) auto-scored by subagent:")
            for asc in auto_scored:
                score_labels = {0: "again", 1: "hard", 2: "good", 3: "easy"}
                label = score_labels.get(asc['score'], str(asc['score']))
                parts.append(f"  - Flashcard {asc['id']}: {label} ({asc['score']}/3) — {asc['feedback']}")
        if auto_cards and not auto_scored:
            parts.append(f"{len(auto_cards)} card(s) marked 'auto' but scorer failed — not recorded.")
        if again_ids:
            parts.append(f"{len(again_ids)} card(s) marked 'again' (requeued): {again_ids}.")
        if new_queue:
            parts.append(f"Flashcard queue: {len(new_queue)} remaining.")
        else:
            parts.append("Flashcard queue empty.")

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
        "present_flashcards": present_flashcards_tool,
        "complete_review_session": complete_review_session_tool,
        "save_review_summary": save_review_summary_tool,
        "inspect_review_state": inspect_review_state_tool,
        "clear_review_state": clear_review_state_tool,
    }
