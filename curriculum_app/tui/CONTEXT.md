# curriculum_app/tui/

Textual-based terminal user interface. Provides a chat-style interface with slash commands for entering different modes.

## Files

- **app.py** — `CurriculumApp(App)`: the main Textual application. Creates the shared `AppState` and pushes the `ChatScreen` on mount.
- **state.py** — `AppState` dataclass holding mutable session state: current `Mode`, active `Curriculum`/`Topic`, and `chat_history`. Also defines `ChatMessage` and the `Mode` enum (IDLE, LEARN, REVIEW).
- **commands.py** — `parse_input()` detects slash commands and returns a `ParsedCommand(name, args)` or `None` for regular chat text. `COMMANDS` is a `dict[str, Command]` registry mapping command names to `Command(name, description, handler)` dataclasses. Handlers are standalone `async (AppState, str) -> str` functions so they can be invoked by both the TUI and the agent layer (as tools). `/quit` is intentionally excluded from the registry — it is TUI-only and handled directly by the chat screen.
- **`__main__.py`** — Entry point: `uv run python -m curriculum_app.tui`.

## Subpackages

- **screens/** — Textual `Screen` subclasses. Currently contains `chat.py` (the main chat screen with message area, input box, and status bar). Future screens: context selection, commit workflow, review, options.
- **widgets/** — Reusable Textual widgets:
  - `status_bar.py` — `StatusBar(Static)` with reactive `mode` and `context` properties.
  - `message.py` — `MessageWidget(Static)` for rendering a single chat message with role-based styling.
