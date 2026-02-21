# rhizome/tui/widgets/

Reusable Textual widgets shared across screens.

## Files

- **chat_pane.py** — `ChatPane(Widget)`: core chat UI containing the message area, chat input, and command palette. Holds chat state (`messages`, `_agent_busy`, `_agent_worker`) and all message/command/topic-tree handlers. Composed by `ChatScreen`.
- **status_bar.py** — `StatusBar(Static)`: persistent bar at the bottom of the chat screen with reactive `mode` and `context` properties.
- **message.py** — `ChatMessage(Markdown)`: renders a single chat message with markdown support, a role prefix (`you` / `agent`), and role-based CSS class for styling.
- **thinking.py** — `ThinkingIndicator(Static)`: animated braille-spinner shown while awaiting the agent's first token.
- **topic_tree.py** — `TopicTree(Tree[Topic])`: interactive topic browser. Loads root topics on mount, lazily loads children on expand. Posts `TopicSelected(topic)` on Enter and `Dismissed()` on Ctrl+Enter.
- **command_palette.py** — `CommandPalette(Widget)`: autocomplete dropdown for slash commands. Shown when input starts with `/`, filters by prefix, supports arrow-key navigation and Tab/Enter selection. Posts `CommandSelected(name)` when a command is chosen.
