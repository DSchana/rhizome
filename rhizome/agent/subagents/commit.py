"""Commit subagent: proposes knowledge entries from selected conversation messages."""

import json
from typing import Any

from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field
from langchain.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command, interrupt

from rhizome.agent.builder import build_agent
from rhizome.agent.state import CommitProposalEntry
from rhizome.agent.system_prompt import KNOWLEDGE_ENTRIES_GUIDE
from rhizome.agent.subagents.base import StructuredSubagent
from rhizome.agent.tools.database import build_database_tools
from rhizome.agent.tools.visibility import ToolVisibility, tool_visibility
from rhizome.db.models import EntryType
from rhizome.db.operations import create_entry, get_topic
from rhizome.logs import get_logger
from rhizome.tui.commit_state import CommitApproved

_logger = get_logger("agent.commit")

COMMIT = "__commit"

COMMIT_SYSTEM_PROMPT = """\
You are a knowledge extraction assistant for a knowledge management system.

Given a set of conversation messages from a learning session, your task is to propose
structured knowledge entries to commit to the database. Each entry should capture a
discrete, self-contained piece of knowledge from the conversation.

You have access to database tools to query existing topics and entries so you can:
- Determine which topic_id to assign each entry to
- Avoid creating duplicate entries
- Understand the existing knowledge structure

## What makes a good knowledge entry

""" + KNOWLEDGE_ENTRIES_GUIDE + """

## Response format

Respond ONLY with a JSON object in this exact format — no additional text, no explanations,
no commentary about your planning steps:
{
    "entries": [
        {
            "title": "Short descriptive title",
            "content": "Full content of the knowledge entry",
            "entry_type": "fact|exposition|overview",
            "topic_id": <integer topic ID>
        }
    ]
}
"""


class KnowledgeEntryProposalSchema(BaseModel):
    title: str
    content: str
    entry_type: str
    topic_id: int


class CommitProposalResponseSchema(BaseModel):
    entries: list[KnowledgeEntryProposalSchema]


class CommitEntryEdit(BaseModel):
    """Partial update to a single entry in the commit proposal."""
    id: int = Field(description="Stable ID of the entry to edit")
    title: str | None = Field(default=None, description="New title (omit to keep current)")
    content: str | None = Field(default=None, description="New content (omit to keep current)")
    entry_type: str | None = Field(default=None, description="New entry type: fact, exposition, or overview (omit to keep current)")
    topic_id: int | None = Field(default=None, description="New topic ID (omit to keep current)")


def _build_commit_diff(
    original: list[dict],
    returned: list[dict],
    originals_by_id: dict[int, dict],
) -> list[str]:
    """Compare original proposal entries against widget-returned entries.

    Returns a list of human-readable lines describing exclusions and edits.
    """
    returned_ids = {e["id"] for e in returned}
    original_ids = {e["id"] for e in original}

    parts: list[str] = []

    # Exclusions
    excluded_ids = sorted(original_ids - returned_ids)
    if excluded_ids:
        labels = [f"entry {eid} ({originals_by_id[eid]['title']!r})" for eid in excluded_ids]
        parts.append(f"Excluded by user: {', '.join(labels)}")

    # Per-entry edits
    for entry in returned:
        entry_id = entry["id"]
        orig = originals_by_id[entry_id]
        changed: list[str] = []
        if entry["title"] != orig["title"]:
            changed.append("title")
        if entry["content"] != orig["content"]:
            changed.append("content")
        if entry["entry_type"] != orig["entry_type"]:
            changed.append("entry_type")
        if entry["topic_id"] != orig["topic_id"]:
            changed.append("topic_id")
        if changed:
            parts.append(f"Entry {entry_id}: user edited {', '.join(changed)}")

    if not parts:
        parts.append("No direct edits or exclusions by user.")

    return parts


def build_commit_subagent(session_factory, chat_pane, **agent_kwargs) -> StructuredSubagent:
    """Build the commit StructuredSubagent with filtered DB tools."""
    tools = list(build_database_tools(session_factory).values())

    provider = agent_kwargs.pop("provider", "anthropic")
    model_name = agent_kwargs.pop("model_name", "claude-sonnet-4-6")

    model, agent, _middleware = build_agent(
        tools,
        provider=provider,
        model_name=model_name,
        response_format=ProviderStrategy(CommitProposalResponseSchema),
        **{**agent_kwargs, "temperature": 0.1},
    )

    return StructuredSubagent(
        model=model,
        agent=agent,
        system_prompt=COMMIT_SYSTEM_PROMPT,
        stateful=True,
        config=None,
        response_schema=CommitProposalResponseSchema,
    )


def build_commit_subagent_tools(
    session_factory, 
    chat_pane, 
    subagent: StructuredSubagent
) -> list:
    """Build the tools the root agent sees for the commit workflow.

    These tools allow the root agent to invoke the commit subagent or
    propose entries directly, present proposals to the user, and write
    approved entries to the DB.  Proposal and payload state are stored
    in ``RhizomeAgentState`` (``commit_proposal`` and ``commit_payload``
    fields) and accessed via ``ToolRuntime``.
    """
    assert isinstance(subagent, StructuredSubagent), "Expected a StructuredSubagent"
    assert subagent.response_schema is CommitProposalResponseSchema

    @tool("inspect_commit_payload", description=(
        "Return the selected conversation messages that the user chose to commit. "
        "Call this before create_commit_proposal so you can see the message contents "
        "and propose appropriate knowledge entries."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def inspect_commit_payload(runtime: ToolRuntime) -> Command:
        payload = runtime.state.get("commit_payload")
        if not payload:
            return Command(update={
                "messages": [ToolMessage(
                    content=json.dumps({"error": "No commit payload available."}),
                    tool_call_id=runtime.tool_call_id,
                )],
            })
        content = json.dumps({"messages": payload}, indent=2)
        return Command(update={
            "messages": [ToolMessage(content=content, tool_call_id=runtime.tool_call_id)],
        })

    @tool("invoke_commit_subagent", description=(
        "Send selected conversation messages to the commit subagent for knowledge extraction. "
        "The subagent will analyze the messages and propose structured knowledge entries. "
        "Use this for larger or more complex selections that benefit from dedicated processing. "
        "Pass 'context' to include relevant parent conversation context (e.g. the current topic). "
        "Pass 'conversation_id' from a previous response to continue refining the proposal. "
        "Additional instructions are typically only necessary in follow-ups."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def invoke_commit_subagent(
        runtime: ToolRuntime,
        instructions: str | None = None,
        context: str | None = None,
        conversation_id: str | None = None,
    ) -> Command:
        # Build input from the commit payload if this is a fresh conversation.
        input_parts = []

        if conversation_id is None:
            payload = runtime.state.get("commit_payload")
            if payload:
                lines = []
                for entry in payload:
                    parts = []
                    if entry.get("user_context"):
                        parts.append(f"[User prompt]\n{entry['user_context']}")
                    parts.append(f"[Message {entry['index']}]\n{entry['content']}")
                    lines.append("\n".join(parts))
                input_parts.append(
                    "Selected messages for knowledge extraction:\n\n"
                    + "\n\n---\n\n".join(lines)
                )

        if context:
            input_parts.append(f"Additional context:\n{context}")

        if instructions:
            input_parts.append(f"Additional Instructions:\n{instructions}")

        input_text = "\n\n".join(input_parts)
        conv_id, response = await subagent.ainvoke(input_text, conversation_id)

        state_update: dict[str, Any] = {}

        if subagent.structured_response is not None:
            proposal_entries = [
                CommitProposalEntry(
                    id=i,
                    title=e.title,
                    content=e.content,
                    entry_type=e.entry_type,
                    topic_id=e.topic_id,
                )
                for i, e in enumerate(subagent.structured_response.entries)
            ]
            state_update["commit_proposal"] = proposal_entries
            msg = f"Commit proposal staged: {len(proposal_entries)} entry/entries."
            if conv_id is not None:
                msg += f" conversation_id={conv_id}"
            msg += " Call present_commit_proposal to show it to the user."
        else:
            msg = json.dumps({
                "error": "Failed to parse proposal. Check raw response content.",
                "raw_response": response.content,
            }, indent=2, default=str)

        state_update["messages"] = [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)]
        return Command(update=state_update)

    @tool("create_commit_proposal", description=(
        "Directly propose knowledge entries for commit without invoking the commit subagent. "
        "Use this when the selected messages are short and simple enough that you can propose "
        "entries yourself. Call inspect_commit_payload first to see the selected messages."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def create_commit_proposal(
        entries: list[KnowledgeEntryProposalSchema],
        runtime: ToolRuntime,
    ) -> Command:
        if not entries:
            return Command(update={
                "messages": [ToolMessage(
                    content=json.dumps({"error": "No entries provided."}),
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        proposal_entries = [
            CommitProposalEntry(
                id=i, title=e.title, content=e.content,
                entry_type=e.entry_type, topic_id=e.topic_id,
            )
            for i, e in enumerate(entries)
        ]
        msg = f"Commit proposal staged: {len(proposal_entries)} entry/entries. Call present_commit_proposal to show it to the user."
        return Command(update={
            "commit_proposal": proposal_entries,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    @tool("present_commit_proposal", description=(
        "Display the current commit proposal to the user for review. "
        "The user can approve, request edits, reset, or cancel. "
        "If edits requested, use edit_commit_proposal to make targeted "
        "changes (preserving any direct edits the user made), then present again."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def present_commit_proposal(runtime: ToolRuntime) -> Command:
        proposal = runtime.state.get("commit_proposal")
        if not proposal:
            return Command(update={
                "messages": [ToolMessage(
                    content=json.dumps({"error": "No proposal available. Create or invoke a proposal first."}),
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        # Build topic name map for display
        topic_ids = {e["topic_id"] for e in proposal}
        topic_map: dict[int, str] = {}
        async with session_factory() as session:
            for tid in topic_ids:
                topic = await get_topic(session, tid)
                if topic is not None:
                    topic_map[tid] = topic.name

        entries = [dict(e) for e in proposal]

        result = interrupt({
            "type": "commit_proposal",
            "entries": entries,
            "topic_map": topic_map,
        })

        # Result is a dict: {choice, entries, instructions?}
        choice = result["choice"]
        modified_entries = result.get("entries", [])
        new_proposal = [CommitProposalEntry(**e) for e in modified_entries]

        # Build diff summary
        originals_by_id = {e["id"]: e for e in proposal}
        diff_parts = _build_commit_diff(proposal, modified_entries, originals_by_id)

        if choice == "Approve":
            msg_lines = [
                f"User approved {len(new_proposal)} entry/entries.",
                *diff_parts,
                "Call accept_commit_proposal to write them to the database.",
            ]
            return Command(update={
                "commit_proposal": new_proposal,
                "messages": [ToolMessage(
                    content="\n".join(msg_lines),
                    tool_call_id=runtime.tool_call_id,
                )],
            })
        elif choice == "Edit":
            instructions = result.get("instructions", "")
            msg_lines = [
                f"User requested edits: {instructions}",
                *diff_parts,
                f"Proposal state updated ({len(new_proposal)} entry/entries remaining).",
                "Use edit_commit_proposal to make further changes, then "
                "present_commit_proposal to show the revised proposal.",
            ]
            return Command(update={
                "commit_proposal": new_proposal,
                "messages": [ToolMessage(
                    content="\n".join(msg_lines),
                    tool_call_id=runtime.tool_call_id,
                )],
            })
        else:
            return Command(update={
                "commit_proposal": None,
                "messages": [ToolMessage(
                    content="User cancelled the proposal.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

    @tool("edit_commit_proposal", description=(
        "Make targeted edits to the current commit proposal without overwriting it. "
        "Supports in-place edits (partial field updates by stable ID), deletions (by ID), "
        "and additions (new entries appended with auto-assigned IDs). "
        "Processing order: edits, then deletions, then additions. "
        "Call present_commit_proposal afterwards to show the revised proposal to the user."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def edit_commit_proposal(
        runtime: ToolRuntime,
        edits: list[CommitEntryEdit] | None = None,
        additions: list[KnowledgeEntryProposalSchema] | None = None,
        deletions: list[int] | None = None,
    ) -> Command:
        proposal = runtime.state.get("commit_proposal")
        if not proposal:
            return Command(update={
                "messages": [ToolMessage(
                    content=json.dumps({"error": "No commit proposal to edit. Create one first."}),
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        entries = [dict(e) for e in proposal]
        entries_by_id = {e["id"]: e for e in entries}
        changes: list[str] = []

        # 1. Apply edits (by stable id)
        for edit in (edits or []):
            entry = entries_by_id.get(edit.id)
            if entry is None:
                continue
            if edit.title is not None:
                entry["title"] = edit.title
            if edit.content is not None:
                entry["content"] = edit.content
            if edit.entry_type is not None:
                entry["entry_type"] = edit.entry_type
            if edit.topic_id is not None:
                entry["topic_id"] = edit.topic_id
            changes.append(f"edited entry {edit.id}")

        # 2. Apply deletions (by stable id)
        delete_ids = set(deletions or [])
        for did in sorted(delete_ids):
            if did in entries_by_id:
                changes.append(f"deleted entry {did} ({entries_by_id[did]['title']!r})")
        entries = [e for e in entries if e["id"] not in delete_ids]

        # 3. Append additions (assign next available id)
        next_id = max((e["id"] for e in proposal), default=-1) + 1
        for addition in (additions or []):
            entries.append(CommitProposalEntry(
                id=next_id,
                title=addition.title,
                content=addition.content,
                entry_type=addition.entry_type,
                topic_id=addition.topic_id,
            ))
            changes.append(f"added entry {next_id} ({addition.title!r})")
            next_id += 1

        new_proposal = [CommitProposalEntry(**e) for e in entries]
        summary = "; ".join(changes) if changes else "no changes applied"
        msg = f"Commit proposal updated ({len(new_proposal)} entry/entries): {summary}."
        return Command(update={
            "commit_proposal": new_proposal,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    @tool("accept_commit_proposal", description=(
        "Write the accepted commit proposal to the database. "
        "Call this after the user has approved the proposal via present_commit_proposal."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def accept_commit_proposal(runtime: ToolRuntime) -> Command:
        proposal = runtime.state.get("commit_proposal")
        if not proposal:
            return Command(update={
                "messages": [ToolMessage(
                    content=json.dumps({"error": "No proposal to accept."}),
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        created = []
        async with session_factory() as session:
            for e in proposal:
                entry_type = EntryType(e["entry_type"]) if e.get("entry_type") else None
                entry = await create_entry(
                    session,
                    topic_id=e["topic_id"],
                    title=e["title"],
                    content=e["content"],
                    entry_type=entry_type,
                )
                created.append({"id": entry.id, "title": entry.title})
            await session.commit()

        if chat_pane is not None:
            chat_pane.post_message(CommitApproved(count=len(created)))

        msg = f"Committed {len(created)} knowledge entry/entries to the database."
        return Command(update={
            "commit_proposal": None,
            "commit_payload": None,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    return [
        inspect_commit_payload,
        invoke_commit_subagent,
        create_commit_proposal,
        present_commit_proposal,
        edit_commit_proposal,
        accept_commit_proposal,
    ]
