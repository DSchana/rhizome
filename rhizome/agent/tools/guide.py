"""Guide tools — list and load on-demand reference material."""

from __future__ import annotations

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command

from rhizome.agent.guides import GUIDE_REGISTRY
from rhizome.agent.tools.visibility import ToolVisibility, tool_visibility


def build_guide_tools() -> dict:
    """Build guide tools (list and load)."""

    @tool("list_guides", description=(
        "List all available guides with their names and descriptions. "
        "Use this to discover what reference material is available "
        "before loading a specific guide."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def list_guides_tool(runtime: ToolRuntime) -> Command:
        if not GUIDE_REGISTRY:
            return Command(update={
                "messages": [ToolMessage(
                    content="No guides available.",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        lines = [f"- **{g.name}**: {g.description}" for g in GUIDE_REGISTRY.values()]
        return Command(update={
            "messages": [ToolMessage(
                content=f"Available guides ({len(lines)}):\n" + "\n".join(lines),
                tool_call_id=runtime.tool_call_id,
            )],
        })

    @tool("load_guide", description=(
        "Load a guide by name, injecting its reference material into the "
        "conversation. Use list_guides to see what's available. "
        "Guides contain detailed instructions for specific workflows "
        "(e.g. crafting flashcards, commit proposals)."
    ))
    @tool_visibility(ToolVisibility.LOW)
    async def load_guide_tool(guide_name: str, runtime: ToolRuntime) -> Command:
        guide = GUIDE_REGISTRY.get(guide_name)
        if guide is None:
            available = ", ".join(GUIDE_REGISTRY.keys()) or "(none)"
            return Command(update={
                "messages": [ToolMessage(
                    content=f"Guide {guide_name!r} not found. Available: {available}",
                    tool_call_id=runtime.tool_call_id,
                )],
            })

        return Command(update={
            "messages": [ToolMessage(
                content=f"[Guide: {guide.name}]\n\n{guide.content}",
                tool_call_id=runtime.tool_call_id,
            )],
        })

    return {
        "list_guides": list_guides_tool,
        "load_guide": load_guide_tool,
    }
