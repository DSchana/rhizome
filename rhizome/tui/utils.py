"""Shared helpers for the TUI layer."""

import json


def serialize_stream_payload(obj: object) -> str:
    """Best-effort JSON serialization of a stream payload."""
    def _default(o: object) -> object:
        if hasattr(o, "model_dump"):
            return o.model_dump()
        return repr(o)
    return json.dumps(obj, default=_default, ensure_ascii=False)
