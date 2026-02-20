"""Welcome header widget displayed at the top of the chat history."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

ASCII_ART = r"""
    ____  __    _
   / __ \/ /_  (_)___  ____  ____ ___  ___
  / /_/ / __ \/ /_  / / __ \/ __ `__ \/ _ \
 / _, _/ / / / / / /_/ /_/ / / / / / /  __/
/_/ |_/_/ /_/_/ /___/\____/_/ /_/ /_/\___/
"""


class WelcomeHeader(Vertical):
    """ASCII art banner and welcome title shown at the top of the chat."""

    DEFAULT_CSS = """
    WelcomeHeader {
        padding: 1 2;
        width: 1fr;
        height: auto;
        align: center middle;
        border: round rgb(80, 120, 90);
    }
    #welcome-art {
        content-align: center middle;
        width: 1fr;
        height: auto;
        color: $text-muted;
    }
    #welcome-title {
        text-align: center;
        width: 1fr;
        height: auto;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(ASCII_ART, id="welcome-art")
        yield Static("Welcome to Rhizome", id="welcome-title")
