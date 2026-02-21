# rhizome/tui/screens/

Textual `Screen` subclasses — each file corresponds to a major UI state.

## Files

- **chat.py** — `ChatScreen`: wraps a `TabbedContent` containing one or more `TabPane`s, each holding a `ChatPane` (independent chat session). Manages tab lifecycle (`_add_tab`, `/new`, `/close`) and delegates `Ctrl+C` cancellation to the active pane. A `StatusBar` is docked at the bottom. Supports `Ctrl+N` keybinding for new tabs.

Future screens (not yet implemented): context selection, commit workflow, review, options.
