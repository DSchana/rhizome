"""Shared color constants for the TUI layer."""


class Colors:
    """Central registry of RGB color strings used across TUI widgets."""

    # -- Message backgrounds (per role × mode) --

    # Idle mode
    IDLE_USER_BG = "rgb(22, 22, 22)"
    IDLE_AGENT_BG = "rgb(28, 28, 28)"
    IDLE_SYSTEM_BG = "rgb(25, 25, 25)"

    # Learn mode
    LEARN_USER_BG = "rgb(18, 22, 40)"
    LEARN_AGENT_BG = "rgb(22, 26, 45)"

    # Review mode
    REVIEW_USER_BG = "rgb(28, 18, 40)"
    REVIEW_AGENT_BG = "rgb(32, 22, 45)"

    # -- ToolCallList backgrounds (per mode) --

    IDLE_TOOLCALL_BG = "rgb(42, 42, 42)"
    IDLE_TOOLCALL_BORDER = "rgb(56, 56, 56)"

    LEARN_TOOLCALL_BG = "rgb(34, 38, 58)"
    LEARN_TOOLCALL_BORDER = "rgb(48, 52, 72)"

    REVIEW_TOOLCALL_BG = "rgb(42, 34, 58)"
    REVIEW_TOOLCALL_BORDER = "rgb(56, 48, 72)"
