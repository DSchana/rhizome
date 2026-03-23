"""Agent operating modes — control the system prompt and tool visibility.

Each mode defines an allowlist of tools and composes a system prompt from
shared and mode-specific sections.  The ``AgentModeMiddleware`` reads the
active mode on every LLM call and overrides the request accordingly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from rhizome.agent.system_prompt import (
    DEBUG_SECTION,
    IDLE_MODE_SECTION,
    LEARN_MODE_SECTION,
    REVIEW_MODE_SECTION,
    SHARED_APP_OVERVIEW,
    SHARED_APP_OVERVIEW_BRIEF,
    SHARED_DATABASE_CONTEXT,
    SHARED_MODE_SWITCHING,
    SHARED_PREAMBLE,
    SHARED_SETTINGS_AND_BEHAVIOR,
)


# -- Shared tool groups -----------------------------------------------------
# These constants keep the allowlists DRY.  When a new tool is added, add it
# to the appropriate group(s) here.

_DB_READ_TOOLS = frozenset({
    "list_all_topics",
    "show_topics",
    "get_entries",
})

_DB_WRITE_TOOLS = frozenset({
    "create_new_topic",
    "delete_topics",
    "create_entries",
})

_APP_TOOLS = frozenset({
    "set_topic",
    "set_mode",
    "rename_tab",
    "ask_user_input",
    "hint_higher_verbosity",
})

_COMMIT_TOOLS = frozenset({
    "inspect_commit_payload",
    "create_commit_proposal",
    "invoke_commit_subagent",
    "present_commit_proposal",
    "edit_commit_proposal",
    "accept_commit_proposal",
})

_WEB_TOOLS = frozenset({
    "web_search",
    "web_fetch",
})

_DB_SQL_TOOLS = frozenset({
    "describe_database",
    "run_sql_query",
    "run_sql_modification",
})

_FLASHCARD_PROPOSAL_TOOLS = frozenset({
    "create_flashcard_proposal",
    "present_flashcard_proposal",
    "edit_flashcard_proposal",
    "accept_flashcard_proposal",
})

_REVIEW_TOOLS = frozenset({
    "get_review_sessions",
    "set_review_scope",
    "configure_review",
    "list_flashcards",
    "get_flashcards",
    "set_review_flashcards",
    "add_flashcards_to_review",
    "start_review",
    "record_review_interaction",
    "complete_review_session",
    "save_review_summary",
    "inspect_review_state",
    "clear_review_state",
})


def _compose_prompt(*sections: str) -> str:
    return "".join(sections)


# -- Base class --------------------------------------------------------------

class AgentMode(ABC):
    """Defines the system prompt and tool allowlist for an agent operating mode."""

    def __init__(self, *, debug: bool = False) -> None:
        self._debug = debug

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier (matches ``Mode`` enum values)."""

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Complete system prompt for this mode."""

    @property
    @abstractmethod
    def allowed_tools(self) -> frozenset[str]:
        """Set of tool names visible to the LLM in this mode."""

    def is_tool_allowed(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools


# -- Concrete modes ----------------------------------------------------------

class IdleAgentMode(AgentMode):
    """Default mode — the user hasn't entered a specific workflow yet."""

    @property
    def name(self) -> str:
        return "idle"

    @property
    def system_prompt(self) -> str:
        return _compose_prompt(
            SHARED_PREAMBLE, 
            SHARED_APP_OVERVIEW_BRIEF, 
            SHARED_DATABASE_CONTEXT,
            SHARED_MODE_SWITCHING, 
            IDLE_MODE_SECTION, 
            SHARED_SETTINGS_AND_BEHAVIOR,
            *(DEBUG_SECTION,) if self._debug else (),
        )

    @property
    def allowed_tools(self) -> frozenset[str]:
        return _DB_READ_TOOLS  | \
               _DB_WRITE_TOOLS | \
               _APP_TOOLS      | \
               _COMMIT_TOOLS   | \
               _WEB_TOOLS      | \
               _DB_SQL_TOOLS


class LearnAgentMode(AgentMode):
    """Active during learning — teaching, grounding in the KB, and commits."""

    @property
    def name(self) -> str:
        return "learn"

    @property
    def system_prompt(self) -> str:
        return _compose_prompt(
            SHARED_PREAMBLE, 
            SHARED_APP_OVERVIEW, 
            SHARED_DATABASE_CONTEXT,
            SHARED_MODE_SWITCHING, 
            LEARN_MODE_SECTION, 
            SHARED_SETTINGS_AND_BEHAVIOR,
            *(DEBUG_SECTION,) if self._debug else (),
        )

    @property
    def allowed_tools(self) -> frozenset[str]:
        return _DB_READ_TOOLS            | \
               _DB_WRITE_TOOLS           | \
               _APP_TOOLS                | \
               _COMMIT_TOOLS             | \
               _FLASHCARD_PROPOSAL_TOOLS | \
               _WEB_TOOLS                | \
               _DB_SQL_TOOLS


class ReviewAgentMode(AgentMode):
    """Active during review/quiz sessions — full review state machine."""

    @property
    def name(self) -> str:
        return "review"

    @property
    def system_prompt(self) -> str:
        return _compose_prompt(
            SHARED_PREAMBLE,
            SHARED_APP_OVERVIEW_BRIEF,
            SHARED_DATABASE_CONTEXT,
            SHARED_MODE_SWITCHING,
            REVIEW_MODE_SECTION,
            SHARED_SETTINGS_AND_BEHAVIOR,
            *(DEBUG_SECTION,) if self._debug else (),
        )

    @property
    def allowed_tools(self) -> frozenset[str]:
        return _DB_READ_TOOLS            | \
               _APP_TOOLS                | \
               _WEB_TOOLS                | \
               _REVIEW_TOOLS             | \
               _FLASHCARD_PROPOSAL_TOOLS | \
               _DB_SQL_TOOLS


# -- Registry ----------------------------------------------------------------

MODE_REGISTRY: dict[str, type[AgentMode]] = {
    "idle": IdleAgentMode,
    "learn": LearnAgentMode,
    "review": ReviewAgentMode,
}

__all__ = [
    "AgentMode",
    "IdleAgentMode",
    "LearnAgentMode",
    "MODE_REGISTRY",
    "ReviewAgentMode",
]
