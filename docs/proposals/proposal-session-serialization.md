# Session Serialization Plan

## Context

Sessions (chat tabs) are ephemeral — all conversation history, agent state, mode, and topic selection are lost when a tab closes or the app exits. This plan adds a serialization layer so sessions can be saved to disk and fully restored later, including both the view-level chat messages and the agent-level LangChain conversation history.

## Design

### Session file format: JSON

A single `.json` file per session, stored in `~/.config/rhizome/sessions/`. JSON is simple, debuggable, and aligns with the existing JSONC options pattern.

### Schema

```json
{
  "version": 1,
  "saved_at": "2026-03-02T12:00:00Z",
  "tab_name": "Session 1",

  "state": {
    "mode": "idle",
    "active_topic_id": null,
    "topic_path": [],
    "options_overrides": {}
  },

  "view_messages": [
    {"role": "user", "content": "...", "mode": "idle", "rich": false},
    {"role": "agent", "content": "...", "mode": "learn", "rich": false}
  ],

  "agent_history": [
    {"type": "system", "content": "...", ...},
    {"type": "human", "content": "..."},
    {"type": "ai", "content": "...", "tool_calls": [...]}
  ],

  "agent_config": {
    "provider": "anthropic",
    "model_name": "claude-sonnet-4-20250514",
    "agent_kwargs": {}
  }
}
```

- `view_messages` — serialized `ChatMessageData` list (what the user sees)
- `agent_history` — serialized LangChain `BaseMessage` list via `message.model_dump()` (what the agent remembers)
- `agent_config` — provider/model so the agent can be rebuilt with the same settings
- `state` — mode, active topic, session-scoped option overrides

### New module: `rhizome/tui/session_io.py`

This module provides two pure functions (no widget dependencies):

1. **`serialize_session(chat_pane) -> dict`** — Extracts all state from a `ChatPane` and returns the JSON-serializable dict above.

2. **`deserialize_session(data: dict) -> SessionSnapshot`** — Parses JSON dict into a `SessionSnapshot` dataclass containing all the typed fields needed to restore a session. Returns a plain data object (no widget construction).

3. **`save_session(chat_pane, path: Path) -> None`** — Calls `serialize_session` and writes JSON to disk.

4. **`load_session(path: Path) -> SessionSnapshot`** — Reads JSON and calls `deserialize_session`.

### New dataclass: `SessionSnapshot`

```python
@dataclass
class SessionSnapshot:
    tab_name: str
    mode: Mode
    active_topic_id: int | None
    topic_path: list[str]
    options_overrides: dict[str, Any]
    view_messages: list[ChatMessageData]
    agent_history: list[BaseMessage]
    agent_provider: str
    agent_model_name: str | None
    agent_kwargs: dict[str, Any]
```

### Restoring a session in `ChatPane`

Add a method `ChatPane.restore_from_snapshot(snapshot: SessionSnapshot)` that:
1. Sets `session_mode`, `active_topic` (looked up by ID), `_topic_path`
2. Replays `view_messages` by mounting `ChatMessage` widgets (no streaming)
3. Rebuilds `AgentSession` with the saved provider/model/kwargs
4. Replaces `AgentSession._history` with the deserialized LangChain messages
5. Applies session-scoped option overrides

### LangChain message serialization

LangChain messages support `message.model_dump()` → dict and can be reconstructed via `messages_from_dict()` or the `type` discriminator. We'll use:
- **Save**: `[msg.model_dump() for msg in agent_session.history]`
- **Load**: Reconstruct using `langchain_core.messages.messages_from_dict()` or manual dispatch on `type` field

## Files to create/modify

| File | Action |
|------|--------|
| `rhizome/tui/session_io.py` | **Create** — `serialize_session`, `deserialize_session`, `save_session`, `load_session`, `SessionSnapshot` |
| `rhizome/tui/widgets/chat_pane.py` | **Modify** — add `restore_from_snapshot()` method |
| `rhizome/tui/CONTEXT.md` | **Update** — document new module |

## Verification

1. Manually test round-trip: start a session, interact with the agent, save, close tab, load into new tab, verify messages display correctly and agent can continue the conversation.
2. Add a round-trip test to `examples/exercise_tools.py` or a standalone script that creates a session snapshot, serializes to JSON, deserializes, and asserts equality.
