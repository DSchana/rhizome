# TUI Architecture

This document describes the architecture of the curriculum-app TUI. It serves as the primary reference for designing new features and understanding how components interact.

## Overview

The TUI is built on [Textual](https://textual.textualize.io/) and follows a two-layer architecture:

- **Model** (`db/` + `tools/`) — Data and business logic. Pure async functions with no UI knowledge.
- **View** (`tui/screens/` + `tui/widgets/`) — Textual Screens and Widgets that hold authoritative state, contain application logic, and render the UI.

There is no separate ViewModel layer. Screens and Widgets own their state directly, leveraging Textual's built-in reactive system for change notification and its message system for inter-component communication. This keeps the codebase simple and avoids duplicating Textual's machinery.

## Model Layer (`db/` + `tools/`)

The data and business logic layer:

- **`db/models.py`** — SQLAlchemy ORM models (`Curriculum`, `Topic`, `KnowledgeEntry`, etc.)
- **`db/engine.py`** — Async engine/session factory
- **`tools/`** — Pure async functions that accept `AsyncSession` and perform CRUD, search, relation management, etc.

The Model layer has no knowledge of the TUI, Textual, or any UI concern. Screens call into this layer directly when they need to read or write data.

## View Layer (`tui/screens/` + `tui/widgets/`)

Textual `Screen` and `Widget` subclasses. Each Screen or Widget:

- **Holds authoritative state** as `reactive` properties or instance attributes
- **Contains application logic** — input parsing, command dispatch, state guards, async orchestration
- **Calls into the Model layer** directly for data operations
- **Renders state into the DOM** — mounts/removes child widgets, updates text, scrolls
- **Communicates with parent components** via Textual's `Message` system (events bubble up the DOM)
- **Reacts to state changes** via Textual's `watch_*` methods (automatic callbacks when `reactive` properties change)

### Textual features we rely on

| Feature | What it does | How we use it |
|---------|-------------|---------------|
| `reactive` properties | Declare state on a widget; Textual tracks changes | App-level state (`mode`), screen-level state (`is_thinking`) |
| `watch_*` methods | Automatic callback when a `reactive` property changes | Mounting/removing spinner when `is_thinking` changes |
| `Message` classes | Typed events that bubble up the DOM tree | Child widgets (e.g. `ChatInput.Submitted`) notify parent screens |
| `on_<message>` handlers | Convention-based message handling | Screens handle events from their children |
| `run_worker` | Run async tasks without blocking the UI | Agent calls, DB operations |
| CSS queries (`query_one`, `query`) | Find widgets in the DOM | Screens locate child widgets to update them |

## State Ownership

State lives at the level of the component that needs it:

### App-level state (`CurriculumApp`)

```python
class CurriculumApp(App):
    mode = reactive(Mode.IDLE)
    active_curriculum: reactive[Curriculum | None] = reactive(None)
    active_topic: reactive[Topic | None] = reactive(None)

    def on_mount(self) -> None:
        self.push_screen(ChatScreen())
```

The `App` holds state that spans screens: the current mode, the active curriculum/topic context.

### Screen-level state (`ChatScreen`)

```python
class ChatScreen(Screen):
    is_thinking = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[ChatMessage] = []
```

Each Screen holds state specific to its function. `ChatScreen` owns the message history and the thinking indicator. Other screens (e.g. a future `ReviewScreen`) would own their own state.

### Widget-level state

Widgets hold purely presentational state (e.g. a `StatusBar` with reactive `mode` and `context` text properties). They receive data from their parent Screen, either at construction time or via Textual messages.

## Commands

Commands are async functions that take the `CurriculumApp` instance and an args string. This gives them access to the full View tree — they can read/write app-level state, query for screens, and call screen methods.

```python
async def handle_help(app: CurriculumApp, args: str) -> None:
    help_text = _build_help_text(args)
    chat = app.query_one(ChatScreen)
    chat._append_message(ChatMessage(role="agent", content=help_text))

async def handle_learn(app: CurriculumApp, args: str) -> None:
    app.mode = Mode.LEARN
    app.push_screen(LearnContextScreen())
```

Commands are full async functions, so they can perform multi-step interactions:

```python
async def handle_complex_command(app: CurriculumApp, args: str) -> None:
    chat = app.query_one(ChatScreen)
    chat.is_thinking = True

    options = await fetch_options_from_db(...)
    chat.is_thinking = False

    choice = await chat.prompt_user_choice(options)

    chat.is_thinking = True
    result = await do_something_with(choice)
    chat.is_thinking = False

    chat._append_message(ChatMessage(role="agent", content=result))
```

### Agent compatibility

The agent layer runs inside the Textual app and holds a reference to the `CurriculumApp` instance. It calls the same command handler functions as the TUI's slash-command system. From the command's perspective, it doesn't matter who invoked it.

## Screen Switching / Navigation

Screen switching uses Textual's built-in `push_screen` / `pop_screen` API directly. There is no routing abstraction — commands and event handlers call these methods on the `App` when they need to navigate.

```python
async def handle_learn(app: CurriculumApp, args: str) -> None:
    app.mode = Mode.LEARN
    app.push_screen(LearnContextScreen())
```

## Data Flow

The general pattern for any user interaction:

1. **User input** → Textual captures a key/click and a widget posts a `Message`
2. **Event bubbles up** → The parent Screen receives the message via an `on_*` handler
3. **Screen processes** — Parses input, applies guards, routes to the appropriate handler
4. **State update + DOM update** — The handler mutates state and updates the widget tree
5. **Reactive side effects** — If a `reactive` property changed, `watch_*` methods fire automatically

For async operations (agent calls, DB queries):

1. The Screen wraps the async work in `run_worker`
2. Sets a loading flag (e.g. `self.is_thinking = True`) which triggers reactive watchers
3. Awaits the result
4. Clears the loading flag and updates state with the result

## Worked Example: User Submits a Chat Message

### Step 0: Setup

`CurriculumApp` holds app-level reactive state (`mode`, `active_curriculum`, `active_topic`). On mount, it pushes `ChatScreen`, which holds its own state (`messages` list, `is_thinking` flag).

### Step 1: Textual posts `ChatInput.Submitted`

The user presses Ctrl+Enter. The `ChatInput` widget catches the key event internally, clears the text area, and posts a `ChatInput.Submitted` message containing the text. Textual's message bubble system sends this up the DOM: first to `ChatInput` itself (no handler), then to its parent, `ChatScreen`.

### Step 2: ChatScreen receives the event

```python
def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
    text = event.value.strip()
    if not text or self.is_thinking:
        return
    command = parse_input(text)
    if command is not None:
        self._handle_command(command.name, command.args)
    else:
        self._handle_chat(text)
```

The Screen does everything: extracts the value, checks the thinking guard, parses for commands, and routes to the appropriate handler.

### Step 3: ChatScreen updates state and DOM

```python
def _handle_chat(self, text: str) -> None:
    self._append_message(ChatMessage(role="user", content=text))

def _append_message(self, msg: ChatMessage) -> None:
    self.messages.append(msg)
    area = self.query_one("#message-area", VerticalScroll)
    area.mount(MessageWidget(role=msg.role, content=msg.content))
    area.scroll_end(animate=False)
```

State mutation and DOM update happen together in `_append_message`. The method appends to the authoritative message list and mounts the corresponding widget in one step.

## Worked Example: Agent "Thinking" Indicator

When the user sends a chat that triggers an agent response, we show an ephemeral spinner while the agent is working and prevent the user from submitting additional messages until the response arrives.

### The thinking flag

`is_thinking` is a `reactive` property on `ChatScreen`. It serves two purposes:

1. **Guard** — `on_chat_input_submitted` checks `self.is_thinking` and returns early if true, preventing concurrent submissions.
2. **Rendering trigger** — `watch_is_thinking` automatically fires when the value changes, mounting or removing the spinner widget.

```python
class ChatScreen(Screen):
    is_thinking = reactive(False)

    def watch_is_thinking(self, thinking: bool) -> None:
        area = self.query_one("#message-area", VerticalScroll)
        if thinking:
            area.mount(SpinnerWidget(id="thinking-indicator"))
            area.scroll_end(animate=False)
        else:
            indicator = self.query("#thinking-indicator")
            if indicator:
                indicator.first().remove()
```

### The flow

```python
def _handle_chat(self, text: str) -> None:
    self._append_message(ChatMessage(role="user", content=text))

    async def _run() -> None:
        self.is_thinking = True       # watch_is_thinking mounts spinner
        response = await self.agent.send(text)
        self.is_thinking = False      # watch_is_thinking removes spinner
        self._append_message(ChatMessage(role="agent", content=response))

    self.run_worker(_run())
```

Setting `self.is_thinking = True` triggers the watcher, which mounts the spinner. The async worker awaits the agent response. When it completes, setting `self.is_thinking = False` triggers the watcher again, which removes the spinner. Finally, the agent's response is appended as a message.

## Future considerations

If the architecture needs stronger separation (e.g. for testability without Textual, agent decoupling, or cross-UI reuse), see `mvvm-architecture-proposal.md` for a full MVVM approach with a dedicated ViewModel layer and custom observer pattern.
