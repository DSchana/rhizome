# rhizome/tui/screens/

Textual `Screen` subclasses — each file corresponds to a major UI state.

## Files

- **chat.py** — `ChatScreen`: wraps a `TabbedContent` containing one or more `TabPane`s. Defines `ChatTabPane` (wraps `ChatPane` for chat sessions) and `LogTabPane` (wraps `LoggingPane` for log viewing). Manages tab lifecycle (`_add_tab`, `_add_log_tab`, `_close_active_tab`). Provides `active_pane` property (returns any `TabPane`) and `post_feedback(text, severity)` which posts a `UserFeedback` message to the active pane — `ChatTabPane` displays it as a chat message, `LogTabPane` shows a toast. Keybindings: `Ctrl+N` (new tab), `Ctrl+W` (close tab), `Ctrl+G` (open logs in editor), `Shift+Tab` (cycle mode), and others.

Future screens (not yet implemented): context selection, commit workflow, review, options.
