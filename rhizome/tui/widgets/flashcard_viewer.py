"""FlashcardViewer — interactive flashcard review widget with spaced-repetition rating."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TypedDict

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from .navigable import NavigableWidgetMixin

# ---------------------------------------------------------------------------
# Color constants
# ---------------------------------------------------------------------------
_DIM = "rgb(100,100,100)"
_HINT = "rgb(80,80,80)"
_RATING_DIM = "rgb(100,100,100)"
_RATING_HIGHLIGHT = "rgb(255,220,80)"
_SCORED_DIM = "rgb(60,60,60)"


# ---------------------------------------------------------------------------
# Payload type
# ---------------------------------------------------------------------------
class FlashcardItem(TypedDict):
    question: str
    answer: str


# ---------------------------------------------------------------------------
# Per-card state
# ---------------------------------------------------------------------------
class CardState(Enum):
    HIDDEN = auto()     # answer not yet revealed
    REVEALED = auto()   # answer shown, awaiting rating
    SCORED = auto()     # rated (still visible in list for navigation)


# ---------------------------------------------------------------------------
# Rating labels
# ---------------------------------------------------------------------------
_RATINGS: list[tuple[int, str]] = [
    (0, "again"),
    (1, "hard"),
    (2, "good"),
    (3, "easy"),
]


class FlashcardViewer(NavigableWidgetMixin, Widget, can_focus=True):
    """Interactive flashcard study widget with reveal and self-rating."""

    BINDINGS = [
        Binding("space", "reveal_or_rate", "Reveal / Rate good", show=False),
        Binding("0", "rate_0", show=False),
        Binding("1", "rate_1", show=False),
        Binding("2", "rate_2", show=False),
        Binding("3", "rate_3", show=False),
        Binding("ctrl+left", "prev_card", show=False),
        Binding("ctrl+right", "next_card", show=False),
        Binding("escape", "dismiss", show=False),
    ]

    DEFAULT_CSS = """
    FlashcardViewer {
        height: auto;
        layout: vertical;
        padding: 0 1;
    }
    FlashcardViewer #fs-header {
        height: 1;
        margin: 0 0 1 0;
    }
    FlashcardViewer #fs-card {
        border: solid rgb(80,80,120);
        padding: 1 2;
        height: auto;
        margin: 0 4;
    }
    FlashcardViewer #fs-question-label {
        text-style: bold;
        color: rgb(100,100,100);
        margin-bottom: 0;
    }
    FlashcardViewer #fs-question {
        margin: 0 0 1 0;
        color: rgb(200,200,220);
    }
    FlashcardViewer #fs-separator {
        height: 1;
        margin: 0 0 1 0;
        color: rgb(80,80,120);
    }
    FlashcardViewer #fs-answer-label {
        text-style: bold;
        color: rgb(100,100,100);
        margin-bottom: 0;
    }
    FlashcardViewer #fs-answer {
        margin: 0;
        color: rgb(180,220,180);
    }
    FlashcardViewer #fs-reveal-hint {
        color: rgb(80,80,80);
        text-align: center;
        margin: 1 0 0 0;
    }
    FlashcardViewer #fs-ratings {
        height: auto;
        text-align: center;
        margin: 1 0 0 0;
    }
    FlashcardViewer #fs-scored-label {
        text-align: center;
        margin: 1 0 0 0;
    }
    FlashcardViewer #fs-empty {
        color: $text-muted;
        text-style: italic;
        margin: 1 0 0 1;
    }
    FlashcardViewer #fs-done {
        color: rgb(100,200,100);
        text-style: bold;
        text-align: center;
        margin: 2 0;
    }
    """

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    class Dismissed(Message):
        """Posted when the user presses Escape."""

    @dataclass
    class CardRated(Message):
        """Posted when the user rates a card."""
        question: str
        rating: int
        rating_label: str

    class SessionComplete(Message):
        """Posted when all cards have been reviewed."""

    # ------------------------------------------------------------------
    # State (no reactive properties — explicit _refresh_view() calls only)
    # ------------------------------------------------------------------

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cards: list[FlashcardItem] = []
        self._states: list[CardState] = []
        self._scores: list[int | None] = []  # rating per card, None if unscored
        self._index: int = 0
        self._total_original: int = 0

    def compose(self) -> ComposeResult:
        yield Static("", id="fs-header")
        yield Static("", id="fs-empty")
        with Vertical(id="fs-card"):
            yield Static("Question", id="fs-question-label")
            yield Static("", id="fs-question")
            yield Static("", id="fs-separator")
            yield Static("Answer", id="fs-answer-label")
            yield Static("", id="fs-answer")
        yield Static("", id="fs-reveal-hint")
        yield Static("", id="fs-ratings")
        yield Static("", id="fs-scored-label")
        yield Static("", id="fs-done")

    def on_mount(self) -> None:
        self._setup_navigable()
        self._refresh_view()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_flashcards(self, flashcards: list[FlashcardItem]) -> None:
        """Load a list of flashcard dicts and start the study session."""
        self._cards = list(flashcards)
        self._states = [CardState.HIDDEN] * len(flashcards)
        self._scores = [None] * len(flashcards)
        self._index = 0
        self._total_original = len(flashcards)
        self._refresh_view()

    # ------------------------------------------------------------------
    # Rendering — single entry point, no cascading
    # ------------------------------------------------------------------

    def _refresh_view(self) -> None:
        empty = not self._cards
        done = not empty and all(s == CardState.SCORED for s in self._states)

        self.query_one("#fs-empty", Static).display = empty
        self.query_one("#fs-done", Static).display = done
        self.query_one("#fs-header", Static).display = not empty
        self.query_one("#fs-card", Vertical).display = not empty and not done

        if empty:
            self.query_one("#fs-empty", Static).update("(No flashcards loaded)")
            self.query_one("#fs-reveal-hint", Static).display = False
            self.query_one("#fs-ratings", Static).display = False
            self.query_one("#fs-scored-label", Static).display = False
            return

        if done:
            scored_count = len(self._cards)
            self.query_one("#fs-done", Static).update(
                f"Session complete — {scored_count} card{'s' if scored_count != 1 else ''} reviewed"
            )
            self.query_one("#fs-reveal-hint", Static).display = False
            self.query_one("#fs-ratings", Static).display = False
            self.query_one("#fs-scored-label", Static).display = False
            self._render_header()
            return

        state = self._states[self._index]

        self.query_one("#fs-reveal-hint", Static).display = state == CardState.HIDDEN
        self.query_one("#fs-ratings", Static).display = state == CardState.REVEALED
        self.query_one("#fs-scored-label", Static).display = state == CardState.SCORED

        self._render_header()
        self._render_card()
        self._render_below_card()

    def _render_header(self) -> None:
        header = self.query_one("#fs-header", Static)
        text = Text()

        hint = "ctrl+left/right to navigate between cards"
        text.append(hint, style=_HINT)

        counter = f"{self._index + 1}/{len(self._cards)}"
        avail = self.size.width - len(hint) - len(counter) - 2
        if avail > 0:
            text.append(" " * avail)
        text.append(counter, style=_DIM)

        header.update(text)

    def _render_card(self) -> None:
        card = self._cards[self._index]
        state = self._states[self._index]

        self.query_one("#fs-question", Static).update(card["question"])

        # Separator
        card_width = self.query_one("#fs-card", Vertical).size.width
        sep_width = max(card_width - 6, 20)
        self.query_one("#fs-separator", Static).update("─" * sep_width)

        show_answer = state in (CardState.REVEALED, CardState.SCORED)
        self.query_one("#fs-answer-label", Static).display = show_answer
        self.query_one("#fs-answer", Static).display = show_answer
        self.query_one("#fs-separator", Static).display = show_answer

        if show_answer:
            self.query_one("#fs-answer", Static).update(card["answer"])

    def _render_below_card(self) -> None:
        state = self._states[self._index]

        if state == CardState.HIDDEN:
            self.query_one("#fs-reveal-hint", Static).update(
                "Press [bold]space[/bold] to reveal answer"
            )

        elif state == CardState.REVEALED:
            text = Text()
            for i, (num, label) in enumerate(_RATINGS):
                if i > 0:
                    text.append("    ", style=_RATING_DIM)
                text.append(f"{num}", style=f"bold {_RATING_HIGHLIGHT}")
                text.append(f" - {label}", style=_RATING_DIM)
            text.append("    ")
            text.append("[space = good]", style=_HINT)
            self.query_one("#fs-ratings", Static).update(text)

        elif state == CardState.SCORED:
            score = self._scores[self._index]
            label = dict(_RATINGS).get(score, "?") if score is not None else "?"
            scored_count = sum(1 for s in self._states if s == CardState.SCORED)
            text = Text()
            text.append(f"Scored: {label}", style=_SCORED_DIM)
            text.append(f"  ({scored_count}/{len(self._cards)} complete)", style=_HINT)
            self.query_one("#fs-scored-label", Static).update(text)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_reveal_or_rate(self) -> None:
        if not self._cards:
            return

        state = self._states[self._index]
        if state == CardState.HIDDEN:
            self._states[self._index] = CardState.REVEALED
            self._refresh_view()
        elif state == CardState.REVEALED:
            self._rate(2)  # "good"
        # SCORED: space does nothing

    def action_rate_0(self) -> None:
        if self._cards and self._states[self._index] == CardState.REVEALED:
            self._rate(0)

    def action_rate_1(self) -> None:
        if self._cards and self._states[self._index] == CardState.REVEALED:
            self._rate(1)

    def action_rate_2(self) -> None:
        if self._cards and self._states[self._index] == CardState.REVEALED:
            self._rate(2)

    def action_rate_3(self) -> None:
        if self._cards and self._states[self._index] == CardState.REVEALED:
            self._rate(3)

    def action_prev_card(self) -> None:
        if self._cards and self._index > 0:
            self._index -= 1
            self._refresh_view()

    def action_next_card(self) -> None:
        if self._cards and self._index < len(self._cards) - 1:
            self._index += 1
            self._refresh_view()

    def action_dismiss(self) -> None:
        self.deactivate()
        self.post_message(self.Dismissed())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rate(self, rating: int) -> None:
        """Process a rating for the current card."""
        card = self._cards[self._index]
        label = dict(_RATINGS).get(rating, "?")
        self.post_message(self.CardRated(
            question=card["question"], rating=rating, rating_label=label,
        ))

        if rating == 0:
            # "again" — reset card state and move to end of list
            self._cards.append(self._cards.pop(self._index))
            self._states.append(CardState.HIDDEN)
            self._states.pop(self._index)
            self._scores.append(None)
            self._scores.pop(self._index)
            # Index now points to the next card (which slid into this position)
            if self._index >= len(self._cards):
                self._index = 0
        else:
            # Mark scored and advance to next unscored card
            self._states[self._index] = CardState.SCORED
            self._scores[self._index] = rating
            self._advance_to_next_unscored()

        # Check completion
        if all(s == CardState.SCORED for s in self._states):
            self._refresh_view()
            self.post_message(self.SessionComplete())
            return

        self._refresh_view()

    def _advance_to_next_unscored(self) -> None:
        """Move index to the next unscored card, wrapping around. Stay put if all scored."""
        n = len(self._cards)
        for offset in range(1, n + 1):
            candidate = (self._index + offset) % n
            if self._states[candidate] != CardState.SCORED:
                self._index = candidate
                return
        # All scored — stay where we are (completion check will handle it)

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def on_resize(self) -> None:
        if self._cards:
            self._refresh_view()
