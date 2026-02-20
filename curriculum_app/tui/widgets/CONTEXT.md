# curriculum_app/tui/widgets/

Reusable Textual widgets shared across screens.

## Files

- **status_bar.py** — `StatusBar(Static)`: persistent bar at the bottom of the chat screen with reactive `mode` and `context` properties.
- **message.py** — `ChatMessage(Markdown)`: renders a single chat message with markdown support, a role prefix (`you` / `agent`), and role-based CSS class for styling.
- **thinking.py** — `ThinkingIndicator(Static)`: animated braille-spinner shown while awaiting the agent's first token.
- **topic_tree.py** — `TopicTree(Tree[Topic])`: interactive topic browser. Loads root topics on mount, lazily loads children on expand. Posts `TopicSelected(topic)` on Enter and `Dismissed()` on Ctrl+Enter.
