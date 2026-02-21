# rhizome/tui/screens/

Textual `Screen` subclasses — each file corresponds to a major UI state.

## Files

- **chat.py** — `ChatScreen`: thin wrapper that composes a `ChatPane` (from `rhizome.tui.widgets.chat_pane`) and a `StatusBar`. Delegates `Ctrl+C` cancellation to the pane and wires app-level reactive properties (`mode`, `context`) to the status bar.

Future screens (not yet implemented): context selection, commit workflow, review, options.
