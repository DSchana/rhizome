"""Commit subagent: proposes knowledge entries from selected conversation messages."""

import json
from typing import Any

from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import ToolMessage
from pydantic import BaseModel
from langchain.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command, interrupt

from rhizome.agent.builder import build_agent
from rhizome.agent.state import CommitProposalEntry
from rhizome.agent.system_prompt import KNOWLEDGE_ENTRIES_GUIDE
from rhizome.agent.subagent import StructuredSubagent
from rhizome.agent.tools import build_tools, ToolGroups, tool_visibility, ToolVisibility
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


def build_commit_subagent(session_factory, chat_pane, **agent_kwargs) -> StructuredSubagent:
    """Build the commit StructuredSubagent with filtered DB tools."""
    tools = build_tools(session_factory, chat_pane=chat_pane, included=ToolGroups.DATABASE)

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


def build_commit_subagent_tools(session_factory, chat_pane, subagent: StructuredSubagent) -> list:
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
                    title=e.title,
                    content=e.content,
                    entry_type=e.entry_type,
                    topic_id=e.topic_id,
                )
                for e in subagent.structured_response.entries
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
                title=e.title, content=e.content,
                entry_type=e.entry_type, topic_id=e.topic_id,
            )
            for e in entries
        ]
        msg = f"Commit proposal staged: {len(proposal_entries)} entry/entries. Call present_commit_proposal to show it to the user."
        return Command(update={
            "commit_proposal": proposal_entries,
            "messages": [ToolMessage(content=msg, tool_call_id=runtime.tool_call_id)],
        })

    @tool("present_commit_proposal", description=(
        "Display the current commit proposal to the user for review. "
        "The user can choose to accept, reject, or request revisions."
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

        if choice == "Approve":
            new_proposal = [CommitProposalEntry(**e) for e in modified_entries]
            return Command(update={
                "commit_proposal": new_proposal,
                "messages": [ToolMessage(
                    content="User approved the proposal.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })
        elif choice == "Edit":
            new_proposal = [CommitProposalEntry(**e) for e in modified_entries]
            instructions = result.get("instructions", "")
            return Command(update={
                "commit_proposal": new_proposal,
                "messages": [ToolMessage(
                    content=f"User requested edits: {instructions}",
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
        accept_commit_proposal,
    ]
