# curriculum_app/tui/screens/

Textual `Screen` subclasses — each file corresponds to a major UI state.

## Files

- **chat.py** — `ChatScreen`: the primary screen with a scrollable message area, text input, and status bar. Routes slash commands (checking for `/quit` directly, then looking up the `COMMANDS` registry) and appends regular chat messages to `AppState.chat_history`. Command handlers are called via `run_worker` since they are async.

Future screens (not yet implemented): context selection, commit workflow, review, options.
