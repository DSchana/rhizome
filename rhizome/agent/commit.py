"""Commit subagent: proposes knowledge entries from selected conversation messages."""

import json
from typing import Any

from langchain.agents.structured_output import ProviderStrategy
from pydantic import BaseModel
from langchain.tools import tool
from langgraph.types import interrupt

from rhizome.agent.builder import build_agent
from rhizome.agent.subagent import StructuredSubagent
from rhizome.agent.tools import build_tools, ToolGroups, tool_visibility, ToolVisibility
from rhizome.db.models import EntryType
from rhizome.db.operations import create_entry
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

When you are ready to propose entries, respond with a JSON object in this exact format:
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

Guidelines:
- Each entry should be self-contained and focused on a single concept
- Use "fact" for discrete, testable pieces of knowledge
- Use "exposition" for explanatory content or detailed descriptions
- Use "overview" for high-level summaries of a topic area
- Always verify topic_id exists by querying the database first
- Respond ONLY with the JSON object, no additional text. Do not include any explanations or commentary outside the JSON,
  including messages explaining your own planning steps.
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

    model, agent = build_agent(
        tools,
        provider=provider,
        model_name=model_name,
        skip_middleware=["InjectUserSettingsMiddleware"],
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

    These tools allow the root agent to invoke the commit subagent,
    present proposals to the user, and write approved entries to the DB.
    """
    assert isinstance(subagent, StructuredSubagent), "Expected a StructuredSubagent"
    assert subagent.response_schema is CommitProposalResponseSchema

    @tool("invoke_commit_subagent", description=(
        "Send selected conversation messages to the commit subagent for knowledge extraction. "
        "The subagent will analyze the messages and propose structured knowledge entries. "
        "Pass 'context' to include relevant parent conversation context (e.g. the current topic). "
        "Pass 'conversation_id' from a previous response to continue refining the proposal. "
        "Additional instructions are typically only necessary in follow-ups."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def invoke_commit_subagent(
        instructions: str | None = None,
        context: str | None = None,
        conversation_id: str | None = None,
    ) -> str:
        # Build input from the commit payload if this is a fresh conversation.
        input_parts = []

        if conversation_id is None and chat_pane is not None:
            payload = chat_pane._commit.commit_payload
            if payload:
                lines = []
                for entry in payload:
                    lines.append(f"[Message {entry['index']}]\n{entry['content']}")
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

        output: dict[str, Any] = {}
        if conv_id is not None:
            output["conversation_id"] = conv_id

        if subagent.structured_response is not None:
            output["proposal"] = {
                "entries": [
                    {
                        "title": e.title,
                        "content": e.content,
                        "entry_type": e.entry_type,
                        "topic_id": e.topic_id,
                    }
                    for e in subagent.structured_response.entries
                ]
            }
        else:
            output["error"] = "Failed to parse proposal. Check raw response content."
            output["raw_response"] = response.content

        return json.dumps(output, indent=2, default=str)


    @tool("present_commit_proposal", description=(
        "Display the commit subagent's current proposal to the user for review. "
        "The user can choose to accept, reject, or request revisions."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def present_commit_proposal() -> str:
        if subagent.structured_response is None:
            return json.dumps({"error": "No proposal available. Invoke the commit subagent first."})

        lines = []
        for i, e in enumerate(subagent.structured_response.entries, 1):
            lines.append(f"{i}. **{e.title}** ({e.entry_type}, topic {e.topic_id})")
            lines.append(f"   {e.content[:120]}{'...' if len(e.content) > 120 else ''}")

        message = "## Proposed Knowledge Entries\n\n" + "\n".join(lines)
        result = interrupt({"message": message, "options": ["Approve All", "Edit", "Cancel"]})
        return f"User selected: {result}"


    @tool("accept_commit_proposal", description=(
        "Write the accepted commit proposal to the database. "
        "Call this after the user has approved the proposal via present_commit_proposal."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def accept_commit_proposal() -> str:
        if chat_pane is None:
            return json.dumps({"error": "Chat pane not available for accessing selected messages."})
        if subagent.structured_response is None:
            return json.dumps({"error": "No proposal to accept."})

        created = []
        async with session_factory() as session:
            for e in subagent.structured_response.entries:
                entry_type = EntryType(e.entry_type) if e.entry_type else None
                entry = await create_entry(
                    session,
                    topic_id=e.topic_id,
                    title=e.title,
                    content=e.content,
                    entry_type=entry_type,
                )
                created.append({"id": entry.id, "title": entry.title})
            await session.commit()

        chat_pane.post_message(CommitApproved(count=len(created)))

        return json.dumps({"created": created}, indent=2)

    return [
        invoke_commit_subagent, 
        present_commit_proposal, 
        accept_commit_proposal
    ]
