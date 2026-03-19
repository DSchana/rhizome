"""Tool infrastructure and builders for the rhizome agent.

Re-exports
----------
- ``ToolVisibility``, ``TOOL_VISIBILITY``, ``tool_visibility`` — visibility system

Domain-specific tool builders live in submodules:
- ``tools.database`` — topic and entry CRUD tools
- ``tools.app`` — app control tools (mode switching, tab renaming, etc.)
- ``tools.sql`` — SQL exploration/modification tools
- ``tools.flashcard`` — flashcard proposal tools
- ``tools.review`` — review session state machine tools
"""

from rhizome.agent.tools.visibility import TOOL_VISIBILITY, ToolVisibility, tool_visibility

__all__ = [
    "TOOL_VISIBILITY",
    "ToolVisibility",
    "tool_visibility",
]
