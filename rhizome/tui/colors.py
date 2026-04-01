"""Shared color constants for the TUI layer."""


class Colors:
    """Central registry of RGB color strings used across TUI widgets."""

    # -- Message backgrounds --
    USER_BG = "rgb(22, 22, 22)"

    # -- Role prefix colors --
    USER_PREFIX = "rgb(100, 160, 230)"
    AGENT_PREFIX = "rgb(200, 100, 200)"
    SYSTEM_PREFIX = "rgb(140, 140, 140)"
    TOOLCALL_TITLE = "rgb(220, 160, 80)"
    SYSTEM_ERROR = "rgb(220, 80, 80)"

    # -- Mode colors --
    LEARN_AGENT_BORDER = "rgb(60, 80, 160)"
    LEARN_SYSTEM_TEXT = "rgb(110, 140, 240)"
    REVIEW_AGENT_BORDER = "rgb(120, 60, 160)"
    REVIEW_SYSTEM_TEXT = "rgb(170, 90, 220)"

    # -- Shell mode --
    SHELL_BORDER = "rgb(200, 60, 60)"

    # -- Commit selection borders --
    COMMIT_SELECTABLE = "rgb(140, 120, 50)"
    COMMIT_CURSOR = "rgb(220, 190, 60)"
    COMMIT_SELECTED = "rgb(60, 160, 80)"
    COMMIT_SELECTED_CURSOR = "rgb(80, 200, 100)"
