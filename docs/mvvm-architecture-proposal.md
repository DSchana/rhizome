# MVVM Architecture Proposal

This document describes a potential MVVM (Model-View-ViewModel) architecture for the curriculum-app TUI. This approach introduces a dedicated ViewModel layer between the Model (`db/` + `tools/`) and the View (`tui/screens/` + `tui/widgets/`), providing a clean separation between state management and rendering. This is not currently implemented — it is a reference for future consideration if the fused architecture (see `architecture.md`) proves insufficient as complexity grows.

## When to consider this approach

- Business logic in Screens/Widgets becomes hard to follow or test
- The agent layer needs to invoke commands without coupling to Textual's runtime
- Multiple Views need to share and react to the same state
- Unit testing business logic without Textual's test harness becomes important

## Layer Definitions

### Model (`db/` + `tools/`)

The data and business logic layer:

- **`db/models.py`** — SQLAlchemy ORM models (`Curriculum`, `Topic`, `KnowledgeEntry`, etc.)
- **`db/engine.py`** — Async engine/session factory
- **`tools/`** — Pure async functions that accept `AsyncSession` and perform CRUD, search, relation management, etc.

The Model layer has no knowledge of the TUI, Textual, or any UI concern.

### ViewModel (`tui/view_models/`)

Each screen gets a corresponding ViewModel class. ViewModels:

- Hold the **authoritative state** for their screen (message list, current mode, loading flags, etc.)
- Expose **actions** — async methods the View calls in response to user input
- Call into the Model layer (tool functions) to read/write data
- **Never** import or reference Textual widgets, screens, or DOM concepts
- Notify the View of state changes via a typed observer pattern (see "View-ViewModel Bridge" below)
- Form a **composition tree** rooted at `AppViewModel` (see "ViewModel Tree" below)

### View (`tui/screens/` + `tui/widgets/`)

Textual `Screen` and `Widget` subclasses. Views:

- Own a ViewModel instance
- Translate Textual events (key presses, button clicks, custom messages) into ViewModel action calls
- Listen for ViewModel state-change notifications and update the widget tree accordingly
- **Never** call tool functions or make business decisions directly
- **Never** mutate ViewModel state directly — always go through action methods

## View-ViewModel Bridge

The ViewModel needs a way to tell the View that state has changed, without importing Textual. This is achieved with a **typed observer pattern** built into a lightweight base class.

### BaseViewModel

All ViewModels inherit from `BaseViewModel`, which provides subscribe/notify:

```python
class BaseViewModel:
    def __init__(self) -> None:
        self._listeners: dict[type, list[Callable]] = {}

    def subscribe(self, event_type: type, handler: Callable) -> None:
        self._listeners.setdefault(event_type, []).append(handler)

    def _notify(self, event: object) -> None:
        for handler in self._listeners.get(type(event), []):
            handler(event)
```

### ViewModel Events

Events are plain dataclasses — **not** Textual `Message`s. They have zero dependency on Textual and live in a shared module (e.g. `tui/events.py`):

```python
@dataclass
class MessagesChanged:
    messages: list[ChatMessage]

@dataclass
class ThinkingChanged:
    is_thinking: bool

@dataclass
class NavigationRequested:
    route: Route
```

### Wiring: View subscribes to ViewModel

The View subscribes to the events it cares about during setup:

```python
class ChatScreen(Screen):
    def __init__(self, vm: ChatViewModel) -> None:
        super().__init__()
        self.vm = vm
        self.vm.subscribe(MessagesChanged, self._on_messages_changed)
        self.vm.subscribe(ThinkingChanged, self._on_thinking_changed)

    def _on_messages_changed(self, event: MessagesChanged) -> None:
        # mount new MessageWidgets...

    def _on_thinking_changed(self, event: ThinkingChanged) -> None:
        # show/hide spinner...
```

### Why a custom observer instead of Textual's message system?

To post Textual `Message`s, the ViewModel would need to be a `MessagePump` subclass (that's where `post_message` lives), making it a Textual DOM node. This would couple it to Textual's event loop, give it a parent/child DOM relationship, and make it untestable without spinning up a full Textual app. It would also blur the line between "ViewModel state change" and "widget UI event."

The observer pattern keeps ViewModels as plain Python objects: testable with a simple spy callback, no Textual imports required.

## ViewModel Tree

ViewModels form a composition hierarchy rooted at `AppViewModel`. Each parent VM owns its children as attributes:

```python
class AppViewModel(BaseViewModel):
    def __init__(self) -> None:
        super().__init__()
        self.chat = ChatViewModel()
        self.mode = Mode.IDLE
        # future: self.review = ReviewViewModel(), etc.

class ChatViewModel(BaseViewModel):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[ChatMessage] = []
        self.is_thinking: bool = False
```

The View tree mirrors this:

```
CurriculumApp          subscribes to  AppViewModel
  └─ ChatScreen        subscribes to  AppViewModel.chat
       ├─ MessageArea                  (renders from chat.messages)
       └─ StatusBar                    (reads app.mode)
```

Each View subscribes to the ViewModel at its level. `CurriculumApp` creates the `AppViewModel`, then passes `app.chat` to `ChatScreen` when it mounts it.

**Child VMs should not reach up to their parent.** If `ChatViewModel` needs to trigger navigation, it emits an event via `_notify` and the parent — whoever subscribed — decides what to do. This keeps the tree composable and each VM testable in isolation.

## Commands

Commands are async functions that take the root `AppViewModel` and drill down to whatever child VM they need. This makes them callable by both the TUI (via slash input) and the agent layer (as tool calls), since `AppViewModel` is a plain Python object with no Textual dependency.

```python
async def handle_help(app: AppViewModel, args: str) -> None:
    help_text = _build_help_text(args)
    app.chat.post_agent_message(help_text)

async def handle_learn(app: AppViewModel, args: str) -> None:
    app.set_mode(Mode.LEARN)
    app.navigate(Route.LEARN_CONTEXT_SELECT)
```

Commands are full async functions, so they can do multi-step interactions:

```python
async def handle_complex_command(app: AppViewModel, args: str) -> None:
    app.chat.set_thinking(True)

    options = await fetch_options_from_db(...)
    app.chat.set_thinking(False)

    # Post a prompt and wait for the user to pick
    choice = await app.chat.prompt_user_choice(options)

    app.chat.set_thinking(True)
    result = await do_something_with(choice)
    app.chat.set_thinking(False)

    app.chat.post_agent_message(result)
```

## Screen Switching / Navigation

"Which screen is active" is app-level state owned by `AppViewModel`. Individual child VMs don't know about screens.

1. A command (or agent action) calls `app.navigate(Route.LEARN_CONTEXT_SELECT)`
2. `AppViewModel.navigate` emits a `NavigationRequested` event via `_notify`
3. `CurriculumApp` (the Textual `App`, subscribed to `AppViewModel`) handles it
4. `CurriculumApp` creates the target screen's ViewModel (if needed), creates the screen, and pushes it

```python
# View — CurriculumApp
def _on_navigation_requested(self, event: NavigationRequested) -> None:
    match event.route:
        case Route.LEARN_CONTEXT_SELECT:
            vm = LearnContextViewModel()
            self.push_screen(LearnContextScreen(vm))
        case Route.CHAT:
            self.pop_screen()
        ...
```

## Data Flow Invariant

- **Events flow up:** User input → View → ViewModel action
- **Data flows down:** ViewModel state → notification → View rendering

The ViewModel never touches the DOM. The View never makes business decisions.

## Worked Example: User Submits a Chat Message

Traced step-by-step through every layer.

### Step 0: Setup

`CurriculumApp` creates an `AppViewModel` (which owns a `ChatViewModel` as `app.chat`). When `ChatScreen` is mounted, it receives `app.chat` and subscribes to its events. The ViewModel holds the authoritative state (message list, mode, etc.). The View renders from that state.

### Step 1: Textual posts `ChatInput.Submitted`

The user presses Ctrl+Enter. The `ChatInput` widget catches the key event internally, clears the text area, and posts a `ChatInput.Submitted` message containing the text. Textual's message bubble system sends this up the DOM: first to `ChatInput` itself (no handler), then to its parent, `ChatScreen`.

**Layer:** View (ChatInput widget). No MVVM involvement — pure View-level input handling.

### Step 2: ChatScreen receives the event and delegates to the ViewModel

```python
# View — ChatScreen
def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
    text = event.value.strip()
    if not text:
        return
    self.run_worker(self.vm.submit_input(text))
```

The View's job here is:
1. Extract the raw value from the Textual event
2. Trivial validation (empty check)
3. Call a ViewModel method
4. Wrap in `run_worker` because the VM method is async

The View does **not** parse the input, does **not** decide if it's a command, does **not** touch the message list.

**Layer:** View (ChatScreen). Responsibility: translate a Textual event into a ViewModel action call.

### Step 3: The ViewModel processes the input

```python
# ViewModel — ChatViewModel
async def submit_input(self, text: str) -> None:
    command = parse_input(text)
    if command is not None:
        await self._execute_command(command.name, command.args)
    else:
        await self._handle_chat(text)
```

The ViewModel owns the decision logic. It calls `parse_input` (a pure function with no Textual or DB dependency). Based on the result, it routes to the appropriate handler.

**Layer:** ViewModel. Responsibility: orchestration and business decisions.

### Step 4: ViewModel updates its own state

```python
# ViewModel — ChatViewModel
async def _handle_chat(self, text: str) -> None:
    user_msg = ChatMessage(role="user", content=text)
    self.messages.append(user_msg)
    self._notify(MessagesChanged(self.messages))
```

The ViewModel appends a `ChatMessage` to its own list and fires a notification. It does **not** create widgets, mount anything, or scroll.

**Layer:** ViewModel. Responsibility: update authoritative state, notify.

### Step 5: Notification reaches the View

The ViewModel's `_notify` call iterates over subscribers for `MessagesChanged`. `ChatScreen` registered a handler during setup (`self.vm.subscribe(MessagesChanged, self._on_messages_changed)`), so it receives the event.

**Layer:** Bridge (observer pattern). The ViewModel doesn't know who's listening.

### Step 6: The View updates widgets

```python
# View — ChatScreen
def _on_messages_changed(self, event: MessagesChanged) -> None:
    area = self.query_one("#message-area", VerticalScroll)
    existing_count = len(area.children)
    for msg in event.new_messages[existing_count:]:
        area.mount(MessageWidget(role=msg.role, content=msg.content))
    area.scroll_end(animate=False)
```

The View reads the ViewModel's state and reconciles the widget tree. It doesn't decide *what* messages exist — it renders whatever the ViewModel says is there.

**Layer:** View (ChatScreen). Responsibility: translate state into widgets.

### Responsibility Summary

| Step | Layer | What happens | Knows about |
|------|-------|-------------|-------------|
| 1 | View (ChatInput) | Captures keypress, posts `Submitted` | Textual only |
| 2 | View (ChatScreen) | Receives event, calls `vm.submit_input(text)` | ViewModel interface |
| 3 | ViewModel | Parses input, routes to chat vs command | `parse_input`, business logic |
| 4 | ViewModel | Appends `ChatMessage`, fires notification | State + Model types |
| 5 | Bridge | Observer pattern delivers to subscribers | Nothing (it's a subscription) |
| 6 | View (ChatScreen) | Mounts new `MessageWidget`s, scrolls | Widgets, ViewModel state (read-only) |

## Worked Example: Agent "Thinking" Indicator

When the user sends a chat that triggers an agent response, we want to show an ephemeral spinner while the agent is working, and prevent the user from submitting additional messages until the response arrives.

### Why this is ViewModel state

The thinking indicator affects what actions are legal: "don't send while a request is in flight" is a business rule. If the thinking state only lived in the View, the ViewModel couldn't enforce this — the View would have to do its own guard checks, which is business logic leaking into the View.

The ephemeral "thinking" message itself does **not** go into `self.messages` — it's not part of the chat history. It's a transient UI state derived from `is_thinking`. The View mounts/unmounts a spinner widget based on the `ThinkingChanged` notification without polluting the message list.

### The flow

#### Step 1: ViewModel receives chat input (continued from previous example)

After appending the user message and notifying, the ViewModel sets `is_thinking` and notifies:

```python
# ViewModel — ChatViewModel
async def _handle_chat(self, text: str) -> None:
    # Record user message
    user_msg = ChatMessage(role="user", content=text)
    self.messages.append(user_msg)
    self._notify(MessagesChanged(self.messages))

    # Enter thinking state
    self.is_thinking = True
    self._notify(ThinkingChanged(True))

    # Await agent response (slow — network/LLM call)
    response = await self.agent.send(text)

    # Exit thinking state, record agent message
    self.is_thinking = False
    agent_msg = ChatMessage(role="agent", content=response)
    self.messages.append(agent_msg)
    self._notify(ThinkingChanged(False))
    self._notify(MessagesChanged(self.messages))
```

#### Step 2: ViewModel guards against concurrent input

```python
# ViewModel — ChatViewModel
async def submit_input(self, text: str) -> None:
    if self.is_thinking:
        return  # Business rule enforced here, not in the View
    ...
```

The View doesn't need to know *why* input is rejected. The ViewModel simply ignores it.

#### Step 3: View reacts to ThinkingChanged

```python
# View — ChatScreen
def _on_thinking_changed(self, event: ThinkingChanged) -> None:
    area = self.query_one("#message-area", VerticalScroll)
    if event.is_thinking:
        area.mount(SpinnerWidget(id="thinking-indicator"))
        area.scroll_end(animate=False)
    else:
        self.query_one("#thinking-indicator", SpinnerWidget).remove()
```

The View's only job is to show/hide the spinner. The guard logic, the timing of when thinking starts/stops, and the agent call are all ViewModel concerns.
