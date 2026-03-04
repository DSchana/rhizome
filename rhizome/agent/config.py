"""Environment-based configuration for the LLM agent."""

import os


def get_api_key() -> str:
    """Read ANTHROPIC_API_KEY from the environment."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it before launching the app."
        )
    return key
