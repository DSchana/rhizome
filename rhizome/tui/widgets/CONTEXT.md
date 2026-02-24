# rhizome/tui/widgets/

Reusable Textual widgets shared across screens.

## Files

- **chat_pane.py** — `ChatPane(Widget)`: core chat UI containing the message area, chat input, and command palette. Holds per-session state (`messages`, `_agent_busy`, `_agent_worker`, `session_mode`, `session_context`, `active_curriculum`, `active_topic`) and all message/command/topic-tree handlers. Each `ChatPane` instance represents an independent chat session; multiple instances live inside `TabbedContent` tabs in `ChatScreen`.
- **status_bar.py** — `StatusBar(Static)`: persistent bar at the bottom of the chat screen with reactive `mode`, `context`, and `token_usage` (a `TokenUsageData` instance) properties. The token display splits conversation tokens from overhead (system prompt + app-generated `[System]` messages), shown as `tokens: 1,234 (+328)  context usage: 2.3%` where `(+N)` is rendered in a lighter gray. Overhead is computed after each agent turn via `build_lc_messages` + `count_tokens_approximately`.
- **message.py** — `ChatMessage(Markdown)`: renders a single chat message with markdown support, a role prefix (`you` / `agent`), and role-based CSS class for styling.
- **thinking.py** — `ThinkingIndicator(Static)`: animated braille-spinner shown while awaiting the agent's first token.
- **topic_tree.py** — `TopicTree(Tree[Topic])`: interactive topic browser. Loads root topics on mount, lazily loads children on expand. Posts `TopicSelected(topic)` on Enter and `Dismissed()` on Ctrl+Enter.
- **agent_message_harness.py** — `AgentMessageHarness(Widget)`: encapsulates one agent turn's display lifecycle. Manages the ThinkingIndicator → ChatMessage + MarkdownStream transition internally. Methods: `start_thinking()`, `stop_thinking()`, `append(token)` (lazily initializes via `_init_chat_message()`), `post_update(update)` (no-op stub for future tool-call rendering), `finalize() -> str`, `cancel() -> str`. Properties: `chat_message`, `chat_message_body`, `agent_message_started`, `is_thinking`. Mounted synchronously by `ChatPane._handle_chat()` before the agent worker starts; the worker then drives the harness through its lifecycle.
- **command_palette.py** — `CommandPalette(Widget)`: autocomplete dropdown for slash commands. Shown when input starts with `/`, filters by prefix, supports arrow-key navigation and Tab/Enter selection. Posts `CommandSelected(name)` when a command is chosen.
