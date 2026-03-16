"""Credential resolution: env var → local file fallback."""

import json
import os
import stat
from pathlib import Path

from rhizome.config import get_config_dir

_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _credentials_path() -> Path:
    return get_config_dir() / "credentials.json"


def _load() -> dict[str, str]:
    path = _credentials_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, str]) -> None:
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    # Owner read/write only
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def get_api_key(provider: str = "anthropic") -> str | None:
    """Return API key for *provider*, checking env var first then credentials file."""
    env_var = _ENV_VARS.get(provider)
    if env_var:
        val = os.environ.get(env_var)
        if val:
            return val
    return _load().get(f"{provider}_api_key")


def store_api_key(provider: str, key: str) -> None:
    """Write an API key to the credentials file."""
    data = _load()
    data[f"{provider}_api_key"] = key
    _save(data)


def delete_api_key(provider: str) -> None:
    """Remove an API key from the credentials file (swallows missing)."""
    data = _load()
    data.pop(f"{provider}_api_key", None)
    _save(data)


def has_api_key(provider: str = "anthropic") -> bool:
    """Return whether an API key is available for *provider*."""
    return get_api_key(provider) is not None
