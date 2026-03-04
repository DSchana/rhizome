"""Runtime context passed to every tool invocation."""

from dataclasses import dataclass, field


@dataclass
class AgentContext:
    user_settings: dict = field(default_factory=dict)
    """Dynamic user settings injected into model calls via middleware."""
