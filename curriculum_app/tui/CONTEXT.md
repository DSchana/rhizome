# curriculum_app/tui/

Textual-based terminal user interface. Provides a chat-style interface with slash commands for entering different modes.

See `docs/architecture.md` for the overall TUI architecture.

## Files

- **app.py** — `CurriculumApp(App)`: the main Textual application. Holds app-level reactive state (`mode`, `context`, `active_curriculum`, `active_topic`), a `session_factory` for DB access, and pushes the `ChatScreen` on mount.
- **state.py** — Shared types: `Mode` enum (IDLE, LEARN, REVIEW) and `ChatEntry` dataclass.
- **commands.py** — `parse_input()` detects slash commands and returns a `ParsedCommand(name, args)` or `None` for regular chat text. `COMMANDS` is a `dict[str, Command]` registry mapping command names to `Command(name, description, handler)` dataclasses. Handlers are standalone `async (CurriculumApp, str) -> None` functions so they can be invoked by both the TUI and the agent layer. `/quit` is intentionally excluded from the registry — it is TUI-only and handled directly by the chat screen.
- **`__main__.py`** — Entry point: `uv run python -m curriculum_app.tui`.

## Subpackages

- **screens/** — Textual `Screen` subclasses. Currently contains `chat.py` (the main chat screen with message area, input box, and status bar). Future screens: context selection, commit workflow, review, options.
- **widgets/** — Reusable Textual widgets:
  - `status_bar.py` — `StatusBar(Static)` with reactive `mode` and `context` properties, bound to the app's reactive state.
  - `message.py` — `ChatMessage(Markdown)` for rendering a single chat message with markdown support and role-based styling.
  - `thinking.py` — `ThinkingIndicator(Static)` animated spinner shown while awaiting agent response.
  - `chat_input.py` — `ChatInput(TextArea)` that submits on Enter and inserts newlines on Ctrl+Enter.
  - `topic_tree.py` — `TopicTree(Tree[Topic])` for browsing the topic hierarchy. Mounted by the `/explore` command.
