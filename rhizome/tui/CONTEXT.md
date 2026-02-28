# rhizome/tui/

Textual-based terminal user interface. Provides a chat-style interface with slash commands for entering different modes.

See `docs/architecture.md` for the overall TUI architecture.

## Files

- **app.py** — `CurriculumApp(App)`: the main Textual application. Holds a `session_factory` for DB access and a root-scope `Options` instance. Subscribes to `Options.Theme` for automatic theme switching. Pushes the `ChatScreen` on mount. Provides an `active_chat_pane` property to access the currently visible `ChatPane`. All session state (mode, context, curriculum, topic, agent) lives in `ChatPane`, not at the app level. Each `ChatPane` creates its own `AgentSession`.
- **types.py** — Shared types: `Mode` enum (IDLE, LEARN, REVIEW), `Role` enum (USER, AGENT, SYSTEM), and `ChatMessageData` dataclass. Re-exports `TokenUsageData` from `rhizome.agent.utils`.
- **commands.py** — `parse_input()` detects slash commands and returns a `ParsedCommand(name, args)` or `None` for regular chat text. `COMMANDS` is a `dict[str, Command]` registry mapping command names to `Command(name, description, handler)` dataclasses. Handlers are standalone `async (CurriculumApp, str) -> None` functions so they can be invoked by both the TUI and the agent layer. `/quit` is intentionally excluded from the registry — it is TUI-only and handled directly by the chat screen.
- **options.py** — Hierarchical options system with scoped inheritance and pub/sub. Core types: `OptionScope` (Root, Session), `OptionSpec` base class with `ChoicesOptionSpec`, `ConditionalChoicesOptionSpec`, and `IntRangeOptionSpec` subclasses, `OptionNamespace` for dotted grouping, and `OptionsMeta` metaclass that wires `resolved_name` paths. `ConditionalChoicesOptionSpec` provides choices that depend on another option's value (e.g. model choices depend on provider); when the condition changes, dependents auto-reset via pub/sub. The `Options` class serves double duty: class-level `OptionSpec`/`OptionNamespace` members define the schema, while instances hold scoped `_values` dicts with parent/child links for inheritance, async subscriber notifications on change, and JSONC persistence (root scope only). Additionally provides a `post_update()` hook (with `subscribe_post_update()`) for batch notification after a group of option changes completes — used by `AgentSession` to detect provider/model changes without holding a persistent Options reference. Options file lives at `~/.config/rhizome/options.jsonc`.
- **log_handler.py** — `TUILogHandler(logging.Handler)`: bridges Python's `logging` module to the Textual UI. Stores formatted Rich-markup log lines in a `deque(maxlen=2000)` for history replay. On `emit()`, formats the record with colored log levels (DEBUG=dim, INFO=blue, WARNING=yellow, ERROR/CRITICAL=red) and timestamps, appends to the deque, then calls `app.call_from_thread()` to write the line to any registered `LoggingPane` widgets. Created and attached to the `"rhizome"` logger in `CurriculumApp.__init__()`.
- **`__main__.py`** — Entry point: `uv run python -m rhizome.tui`.

## Subpackages

- **screens/** — Textual `Screen` subclasses. Currently contains `chat.py` (the main chat screen with message area, input box, and status bar). `chat.py` also defines `LogTabPane(TabPane)` which composes a `LoggingPane` for the `/logs` command. Future screens: context selection, commit workflow, review, options.
- **widgets/** — Reusable Textual widgets:
  - `status_bar.py` — `StatusBar(Static)` with reactive `mode` and `context` properties, bound to the app's reactive state.
  - `message.py` — `ChatMessage(Widget)` for rendering a single chat message with markdown support, role-based styling, and conditional collapse button (shown only for messages exceeding `COLLAPSE_LINE_THRESHOLD` lines).
  - `thinking.py` — `ThinkingIndicator(Static)` animated spinner shown while awaiting agent response.
  - `chat_input.py` — `ChatInput(TextArea)` that submits on Enter and inserts newlines on Ctrl+Enter.
  - `topic_tree.py` — `TopicTree(Tree[Topic])` for browsing the topic hierarchy. Mounted by the `/explore` command.
  - `options_editor.py` — `OptionsEditor(Widget)` inline widget for editing options. Receives an `Options` instance and uses `WIDGET_BUILDERS` dispatch to create appropriate widgets per spec type. On change, calls `options.set()` directly — pub/sub handles all side effects. Posts `Done` message when dismissed.
