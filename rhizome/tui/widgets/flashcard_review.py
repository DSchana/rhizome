"""FlashcardReview — interrupt-based flashcard review widget for the review agent."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, TypedDict

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static, TextArea

from .interrupt import InterruptWidgetBase

# ---------------------------------------------------------------------------
# Color constants
# ---------------------------------------------------------------------------
_DIM = "rgb(100,100,100)"
_HINT = "rgb(80,80,80)"
_RATING_DIM = "rgb(100,100,100)"
_RATING_HIGHLIGHT = "rgb(255,220,80)"
_SCORED_DIM = "rgb(60,60,60)"
_USER_ANSWER = "rgb(170,175,190)"
_DONE_GREEN = "rgb(100,200,100)"
_CANCEL_RED = "rgb(255,80,80)"
_ID_COLOR = "rgb(80,80,100)"
_COUNTER_ACTUAL = "rgb(70,70,70)"


# ---------------------------------------------------------------------------
# Payload type
# ---------------------------------------------------------------------------
class ReviewCardItem(TypedDict, total=False):
    question: str
    answer: str
    id: int


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
class AgainBehaviour(Enum):
    QUEUE = auto()   # re-queue card at end (default)
    MARK = auto()    # mark as "again" score, don't re-queue


# ---------------------------------------------------------------------------
# Per-card state
# ---------------------------------------------------------------------------
class CardState(Enum):
    HIDDEN = auto()     # answer not yet revealed
    REVEALED = auto()   # answer shown, awaiting rating
    SCORED = auto()     # rated


# ---------------------------------------------------------------------------
# Rating labels
# ---------------------------------------------------------------------------
_RATINGS: list[tuple[int, str]] = [
    (0, "again"),
    (1, "hard"),
    (2, "good"),
    (3, "easy"),
]

# Special score for auto-score mode
AUTO_SCORE = -1
AUTO_SCORE_LABEL = "auto"


# ---------------------------------------------------------------------------
# Answer input
# ---------------------------------------------------------------------------
class _AnswerInput(TextArea):
    """Single-line text area for typing a flashcard answer."""

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, **kwargs) -> None:
        super().__init__(show_line_numbers=False, **kwargs)

    def _on_key(self, event) -> None:
        if event.key == "enter":
            self.post_message(self.Submitted(value=self.text.strip()))
            event.stop()
            event.prevent_default()
        elif event.key == "ctrl+j":
            event.stop()
            event.prevent_default()
        else:
            super()._on_key(event)


class FlashcardReview(InterruptWidgetBase):
    """Interactive flashcard review widget that resolves an interrupt on completion.

    Configurable options:
    - ``user_input_enabled``: show text input for each question (default True)
    - ``counter_start`` / ``counter_total``: override displayed counter
    - ``auto_score``: enter auto-scores instead of showing rating options
    - ``again_behaviour``: ``AgainBehaviour.QUEUE`` (re-queue) or
      ``AgainBehaviour.MARK`` (mark as again score, advance)
    """

    DISABLE_CHILDREN_ON_DEACTIVATE = False

    BINDINGS = [
        Binding("enter", "reveal_or_rate", "Reveal / Rate good", show=False),
        Binding("0", "rate_0", show=False),
        Binding("1", "rate_1", show=False),
        Binding("2", "rate_2", show=False),
        Binding("3", "rate_3", show=False),
        Binding("alt+left", "prev_card", show=False),
        Binding("alt+right", "next_card", show=False),
        Binding("ctrl+c", "cancel_session", show=False),
    ]

    DEFAULT_CSS = """
    FlashcardReview {
        height: auto;
        layout: vertical;
        padding: 0 1;
    }
    FlashcardReview #fr-collapse {
        dock: right;
        width: auto;
        min-width: 3;
        height: 1;
        background: transparent;
        border: none;
        color: $text-muted;
        display: none;
    }
    FlashcardReview #fr-collapse:hover {
        color: $text;
    }
    FlashcardReview #fr-card {
        border: solid rgb(58,65,80);
        padding: 1 2;
        height: auto;
        margin: 0 4;
    }
    FlashcardReview #fr-question-row {
        height: 1;
        margin: 0 0 0 0;
    }
    FlashcardReview #fr-question-label {
        text-style: bold;
        color: rgb(100,100,100);
        width: auto;
    }
    FlashcardReview #fr-counter {
        width: 1fr;
        text-align: right;
    }
    FlashcardReview #fr-question {
        margin: 0 0 1 0;
        color: rgb(195,195,205);
    }
    FlashcardReview #fr-answer-input-label {
        text-style: bold;
        color: rgb(100,100,100);
        margin: 0;
    }
    FlashcardReview #fr-answer-input {
        height: 3;
        margin: 0;
        border: solid rgb(35,38,48);
        background: transparent;
        & .text-area--cursor-line {
            background: transparent;
        }
    }
    FlashcardReview #fr-answer-input:focus {
        border: solid rgb(55,60,72);
    }
    FlashcardReview #fr-user-answer-label {
        text-style: bold;
        color: rgb(100,100,100);
        margin: 0;
    }
    FlashcardReview #fr-user-answer {
        margin: 0 0 1 0;
        color: rgb(170,175,190);
    }
    FlashcardReview #fr-separator {
        height: 1;
        margin: 0 0 1 0;
        color: rgb(58,65,80);
    }
    FlashcardReview #fr-answer-label {
        text-style: bold;
        color: rgb(100,100,100);
        margin-bottom: 0;
    }
    FlashcardReview #fr-answer {
        margin: 0;
        color: rgb(210,200,175);
    }
    FlashcardReview #fr-answer-hidden {
        margin: 0;
        color: rgb(80,80,80);
        text-style: italic;
    }
    FlashcardReview #fr-reveal-hint {
        color: rgb(80,80,80);
        text-align: center;
        margin: 1 0 0 0;
    }
    FlashcardReview #fr-ratings {
        height: auto;
        text-align: center;
        margin: 1 0 0 0;
    }
    FlashcardReview #fr-scored-label {
        text-align: center;
        margin: 1 0 0 0;
    }
    FlashcardReview #fr-empty {
        color: $text-muted;
        text-style: italic;
        margin: 1 0 0 1;
    }
    FlashcardReview #fr-status {
        text-style: bold;
        text-align: center;
        margin: 1 0 0 0;
    }
    """

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    @dataclass
    class CardRated(Message):
        """Posted when the user rates a card."""
        question: str
        answer: str
        user_answer: str
        rating: int
        rating_label: str
        card_id: int | None

    class SessionComplete(Message):
        """Posted when all cards have been reviewed."""

    class SessionCancelled(Message):
        """Posted when the user cancels with ctrl+c."""

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def __init__(
        self,
        cards: list[ReviewCardItem],
        *,
        user_input_enabled: bool = True,
        counter_start: int | None = None,
        counter_total: int | None = None,
        auto_score: bool = False,
        again_behaviour: AgainBehaviour = AgainBehaviour.QUEUE,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._cards: list[ReviewCardItem] = list(cards)
        self._states: list[CardState] = [CardState.HIDDEN] * len(cards)
        self._scores: list[int | None] = [None] * len(cards)
        self._user_answers: list[str] = [""] * len(cards)
        self._index: int = 0
        self._total_original: int = len(cards)

        # Configuration
        self._user_input_enabled = user_input_enabled
        self._counter_start = counter_start
        self._counter_total = counter_total
        self._auto_score = auto_score
        self._again_behaviour = again_behaviour

        # Post-session state
        self._session_done = False
        self._session_cancelled = False
        self._collapsed = False

    def compose(self) -> ComposeResult:
        yield Button("▼", id="fr-collapse")
        yield Static("", id="fr-empty")
        with Vertical(id="fr-card"):
            with Horizontal(id="fr-question-row"):
                yield Static("Question", id="fr-question-label")
                yield Static("", id="fr-counter")
            yield Static("", id="fr-question")
            yield Static("Your answer", id="fr-answer-input-label")
            yield _AnswerInput(id="fr-answer-input")
            yield Static("Your answer", id="fr-user-answer-label")
            yield Static("", id="fr-user-answer")
            yield Static("", id="fr-separator")
            yield Static("Answer", id="fr-answer-label")
            yield Static("", id="fr-answer")
            yield Static("(Answer hidden)", id="fr-answer-hidden")
        yield Static("", id="fr-reveal-hint")
        yield Static("", id="fr-ratings")
        yield Static("", id="fr-scored-label")
        yield Static("", id="fr-status")

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_view()

    def on_focus(self) -> None:
        super().on_focus()
        if (
            self._cards
            and not self._session_done
            and not self._session_cancelled
            and self._user_input_enabled
            and self._states[self._index] == CardState.HIDDEN
        ):
            self.query_one("#fr-answer-input", _AnswerInput).focus()

    # ------------------------------------------------------------------
    # Action gating
    # ------------------------------------------------------------------

    def check_action(self, action: str, parameters: tuple) -> bool:
        # After session end, only allow navigation
        if self._session_done or self._session_cancelled:
            return action in ("prev_card", "next_card")
        return True

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _refresh_view(self) -> None:
        empty = not self._cards
        done = self._session_done
        cancelled = self._session_cancelled
        finished = done or cancelled

        self.query_one("#fr-empty", Static).display = empty
        self.query_one("#fr-card", Vertical).display = (
            not empty and (not finished or not self._collapsed)
        )

        if empty:
            self.query_one("#fr-empty", Static).update("(No flashcards loaded)")
            self.query_one("#fr-reveal-hint", Static).display = False
            self.query_one("#fr-ratings", Static).display = False
            self.query_one("#fr-scored-label", Static).display = False
            self.query_one("#fr-status", Static).display = False
            return

        # Status message
        status = self.query_one("#fr-status", Static)
        if done:
            scored_count = sum(1 for s in self._states if s == CardState.SCORED)
            status.update(
                f"Session complete — {scored_count} card{'s' if scored_count != 1 else ''} reviewed"
            )
            status.styles.color = _DONE_GREEN
            status.display = True
        elif cancelled:
            status.update("Session cancelled")
            status.styles.color = _CANCEL_RED
            status.display = True
        else:
            status.display = False

        if finished and self._collapsed:
            # Collapsed mode — hide card and below-card elements
            self.query_one("#fr-reveal-hint", Static).display = False
            self.query_one("#fr-ratings", Static).display = False
            self.query_one("#fr-scored-label", Static).display = False
            return

        if finished:
            # Expanded finished — show cards for navigation but no interactive elements
            self._render_card()
            self.query_one("#fr-reveal-hint", Static).display = False
            self.query_one("#fr-ratings", Static).display = False
            # Show scored label for the current card if scored
            if self._states[self._index] == CardState.SCORED:
                self.query_one("#fr-scored-label", Static).display = True
                self._render_scored_label()
            else:
                self.query_one("#fr-scored-label", Static).display = False
            return

        # Active session
        state = self._states[self._index]
        self.query_one("#fr-reveal-hint", Static).display = state == CardState.HIDDEN
        self.query_one("#fr-ratings", Static).display = (
            state == CardState.REVEALED and not self._auto_score
        )
        self.query_one("#fr-scored-label", Static).display = state == CardState.SCORED

        self._render_card()
        self._render_below_card()

    def _render_card(self) -> None:
        card = self._cards[self._index]
        state = self._states[self._index]
        finished = self._session_done or self._session_cancelled
        is_again = state == CardState.SCORED and self._scores[self._index] == 0

        # Card border title — nav hint on the right
        card_container = self.query_one("#fr-card", Vertical)
        card_container.border_title = "alt+←/→ to navigate"
        card_container.styles.border_title_align = "right"

        # Question label — include ID if present
        card_id = card.get("id")
        question_label = self.query_one("#fr-question-label", Static)
        if card_id is not None:
            label_text = Text()
            label_text.append("Question", style="bold")
            label_text.append(f" (id: {card_id})", style=_ID_COLOR)
            question_label.update(label_text)
        else:
            question_label.update("Question")

        # Counter inside card (right-aligned)
        self._render_counter()

        self.query_one("#fr-question", Static).update(card["question"])

        # Answer input — visible only when hidden and input enabled and session active
        answer_input = self.query_one("#fr-answer-input", _AnswerInput)
        input_label = self.query_one("#fr-answer-input-label", Static)
        show_input = (
            state == CardState.HIDDEN
            and self._user_input_enabled
            and not finished
        )
        input_label.display = show_input
        answer_input.display = show_input

        if show_input:
            answer_input.clear()
            answer_input.focus()
        elif answer_input.has_focus:
            self.focus()

        # User's submitted answer — visible after reveal (only if input was enabled)
        user_answer_label = self.query_one("#fr-user-answer-label", Static)
        user_answer_display = self.query_one("#fr-user-answer", Static)
        show_user_answer = (
            state in (CardState.REVEALED, CardState.SCORED)
            and not is_again
            and self._user_input_enabled
            and bool(self._user_answers[self._index])
        )
        user_answer_label.display = show_user_answer
        user_answer_display.display = show_user_answer
        if show_user_answer:
            user_answer_display.update(self._user_answers[self._index])

        # Separator and correct answer
        card_width = card_container.size.width
        sep_width = max(card_width - 6, 20)
        self.query_one("#fr-separator", Static).update("─" * sep_width)

        show_answer = state in (CardState.REVEALED, CardState.SCORED) and not is_again
        show_answer_hidden = is_again
        self.query_one("#fr-answer-label", Static).display = show_answer
        self.query_one("#fr-answer", Static).display = show_answer
        self.query_one("#fr-answer-hidden", Static).display = show_answer_hidden
        self.query_one("#fr-separator", Static).display = show_answer or show_answer_hidden

        if show_answer:
            self.query_one("#fr-answer", Static).update(card["answer"])

    def _render_counter(self) -> None:
        counter_widget = self.query_one("#fr-counter", Static)

        # Counter — use overrides if provided
        has_override = self._counter_start is not None and self._counter_total is not None
        if has_override:
            display_index = self._counter_start + self._index
            display_total = self._counter_total
        else:
            display_index = self._index + 1
            display_total = len(self._cards)

        text = Text()
        text.append(f"{display_index}/{display_total}", style=_DIM)

        if has_override:
            actual = f" ({self._index + 1}/{len(self._cards)})"
            text.append(actual, style=_COUNTER_ACTUAL)

        counter_widget.update(text)

    def _render_below_card(self) -> None:
        state = self._states[self._index]

        if state == CardState.HIDDEN:
            if self._user_input_enabled:
                self.query_one("#fr-reveal-hint", Static).update(
                    "Type your answer and press [bold]enter[/bold] to reveal, "
                    "or press [bold]enter[/bold] to reveal directly"
                )
            else:
                self.query_one("#fr-reveal-hint", Static).update(
                    "Press [bold]enter[/bold] to reveal"
                )

        elif state == CardState.REVEALED:
            if self._auto_score:
                # Auto-score mode: just show a hint that enter will advance
                self.query_one("#fr-ratings", Static).display = False
                self.query_one("#fr-reveal-hint", Static).display = True
                self.query_one("#fr-reveal-hint", Static).update(
                    "Press [bold]enter[/bold] to continue"
                )
            else:
                text = Text()
                for i, (num, label) in enumerate(_RATINGS):
                    if i > 0:
                        text.append("    ", style=_RATING_DIM)
                    text.append(f"{num}", style=f"bold {_RATING_HIGHLIGHT}")
                    text.append(f" - {label}", style=_RATING_DIM)
                text.append("    ")
                text.append("[enter = good]", style=_HINT)
                self.query_one("#fr-ratings", Static).update(text)

        elif state == CardState.SCORED:
            self._render_scored_label()

    def _render_scored_label(self) -> None:
        score = self._scores[self._index]
        if score == AUTO_SCORE:
            label = AUTO_SCORE_LABEL
        else:
            label = dict(_RATINGS).get(score, "?") if score is not None else "?"
        scored_count = sum(1 for s in self._states if s == CardState.SCORED)
        text = Text()
        text.append(f"Scored: {label}", style=_SCORED_DIM)
        text.append(f"  ({scored_count}/{len(self._cards)} complete)", style=_HINT)
        self.query_one("#fr-scored-label", Static).update(text)

    # ------------------------------------------------------------------
    # Collapse / expand (post-session only)
    # ------------------------------------------------------------------

    def _set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        btn = self.query_one("#fr-collapse", Button)
        btn.label = "▶" if collapsed else "▼"
        self._refresh_view()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fr-collapse":
            event.stop()
            self._set_collapsed(not self._collapsed)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_reveal_or_rate(self) -> None:
        if not self._cards:
            return

        state = self._states[self._index]
        if state == CardState.HIDDEN:
            self._reveal_current()
        elif state == CardState.REVEALED:
            if self._auto_score:
                self._rate(AUTO_SCORE)
            else:
                self._rate(2)  # "good"

    def _reveal_current(self) -> None:
        if self._user_input_enabled:
            answer_input = self.query_one("#fr-answer-input", _AnswerInput)
            self._user_answers[self._index] = answer_input.text.strip()
        self._states[self._index] = CardState.REVEALED
        self.focus()
        self._refresh_view()

    def action_rate_0(self) -> None:
        if (
            self._cards
            and self._states[self._index] == CardState.REVEALED
            and not self._auto_score
        ):
            self._rate(0)

    def action_rate_1(self) -> None:
        if (
            self._cards
            and self._states[self._index] == CardState.REVEALED
            and not self._auto_score
        ):
            self._rate(1)

    def action_rate_2(self) -> None:
        if (
            self._cards
            and self._states[self._index] == CardState.REVEALED
            and not self._auto_score
        ):
            self._rate(2)

    def action_rate_3(self) -> None:
        if (
            self._cards
            and self._states[self._index] == CardState.REVEALED
            and not self._auto_score
        ):
            self._rate(3)

    def action_prev_card(self) -> None:
        if self._cards and self._index > 0:
            self._index -= 1
            self._refresh_view()

    def action_next_card(self) -> None:
        if self._cards and self._index < len(self._cards) - 1:
            self._index += 1
            self._refresh_view()

    def action_cancel_session(self) -> None:
        if self._session_done or self._session_cancelled:
            return
        self._session_cancelled = True
        # Disable further answer input
        answer_input = self.query_one("#fr-answer-input", _AnswerInput)
        answer_input.display = False
        self.focus()
        self.post_message(self.SessionCancelled())
        self._finish_session(completed=False)

    # ------------------------------------------------------------------
    # Child events
    # ------------------------------------------------------------------

    def on__answer_input_submitted(self, event: _AnswerInput.Submitted) -> None:
        if (
            self._cards
            and not self._session_done
            and not self._session_cancelled
            and self._states[self._index] == CardState.HIDDEN
        ):
            self._reveal_current()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rate(self, rating: int) -> None:
        card = self._cards[self._index]
        if rating == AUTO_SCORE:
            label = AUTO_SCORE_LABEL
        else:
            label = dict(_RATINGS).get(rating, "?")
        self.post_message(self.CardRated(
            question=card["question"],
            answer=card["answer"],
            user_answer=self._user_answers[self._index],
            rating=rating,
            rating_label=label,
            card_id=card.get("id"),
        ))

        if rating == 0:
            if self._again_behaviour == AgainBehaviour.QUEUE:
                # Re-queue at end
                self._cards.append(self._cards.pop(self._index))
                self._states.append(CardState.HIDDEN)
                self._states.pop(self._index)
                self._scores.append(None)
                self._scores.pop(self._index)
                self._user_answers.append("")
                self._user_answers.pop(self._index)
                if self._index >= len(self._cards):
                    self._index = 0
            else:
                # MARK mode — score as "again" and advance
                self._states[self._index] = CardState.SCORED
                self._scores[self._index] = 0
                self._advance_to_next_unscored()
        else:
            self._states[self._index] = CardState.SCORED
            self._scores[self._index] = rating
            self._advance_to_next_unscored()

        # Check completion
        if all(s == CardState.SCORED for s in self._states):
            self._session_done = True
            self.post_message(self.SessionComplete())
            self._finish_session(completed=True)
            return

        self._refresh_view()

    def _advance_to_next_unscored(self) -> None:
        n = len(self._cards)
        for offset in range(1, n + 1):
            candidate = (self._index + offset) % n
            if self._states[candidate] != CardState.SCORED:
                self._index = candidate
                return

    def _finish_session(self, *, completed: bool) -> None:
        """Resolve the interrupt and transition to collapsed post-session state."""
        result = self._build_result(completed=completed)
        self.resolve(result)

        # Re-enable focus for post-session navigation
        self.can_focus = True

        # Show collapse button
        self.query_one("#fr-collapse", Button).display = True
        self._set_collapsed(True)

    def _build_result(self, *, completed: bool) -> dict[str, Any]:
        cards_result = []
        for i, card in enumerate(self._cards):
            score = self._scores[i]
            if score == AUTO_SCORE:
                score_label = AUTO_SCORE_LABEL
            elif score is not None:
                score_label = dict(_RATINGS).get(score, "?")
            else:
                score_label = None
            cards_result.append({
                "id": card.get("id"),
                "question": card["question"],
                "answer": card["answer"],
                "user_answer": self._user_answers[i],
                "score": score,
                "score_label": score_label,
            })
        return {
            "completed": completed,
            "cards": cards_result,
        }

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def on_resize(self) -> None:
        if self._cards:
            self._refresh_view()
