# rhizome/tui/screens/

Textual `Screen` subclasses — each file corresponds to a major UI state.

## Files

- **chat.py** — `ChatScreen`: wraps a `TabbedContent` containing one or more `TabPane`s. Defines `ChatTabPane` (wraps `ChatPane` for chat sessions) and `LogTabPane` (wraps `LoggingPane` for log viewing). Manages tab lifecycle (`_add_tab`, `_add_log_tab`, `_close_active_tab`). Provides `active_pane` property (returns any `TabPane`) and `post_feedback(text, severity)` which posts a `UserFeedback` message to the active pane — `ChatTabPane` displays it as a chat message, `LogTabPane` shows a toast. Keybindings: `Ctrl+N` (new tab), `Ctrl+W` (close tab), `Ctrl+PageUp`/`Ctrl+PageDown` (switch tabs). Chat-pane-specific bindings (`Ctrl+C`, `Ctrl+L`, `Ctrl+T`, `Ctrl+O`, `Shift+Tab`) live on `ChatPane`; `Ctrl+G` (open logs in editor) lives on `LoggingPane`.

Future screens (not yet implemented): context selection, commit workflow, review, options.
