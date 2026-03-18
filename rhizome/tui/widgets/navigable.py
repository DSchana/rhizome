"""NavigableWidgetMixin — shared focus/border/hint behavior for active-stack widgets."""

from __future__ import annotations

from typing import Any

from textual.message import Message


class WidgetDeactivated(Message):
    """Posted by interactive widgets when they are no longer accepting input.

    ChatPane listens for this to remove the widget from the navigable
    active-widget stack.
    """

    def __init__(self, sender: Any) -> None:
        super().__init__()
        self.sender_widget = sender


_NAV_HINT = "ctrl+\u2191/\u2193 to navigate"


class NavigableWidgetMixin:
    """Mixin providing focus-border, navigation hint, and deactivation lifecycle.

    Border styles for the ``.navigable`` CSS class are defined in the App-level
    CSS (``RhizomeApp.CSS``) so they apply globally regardless of widget type.

    Widgets using this mixin should:

    1. Call ``_setup_navigable()`` in ``on_mount`` (or inherit from a base
       that does so).
    2. Call ``deactivate()`` when they are no longer interactable.
    3. Override ``_is_navigable()`` to gate subtitle restoration on blur
       (e.g. return ``False`` once a future has resolved).
    4. Call ``super().on_focus()`` / ``super().on_blur()`` if overriding
       those handlers.
    """

    def _is_navigable(self) -> bool:
        """Return ``True`` while the widget is still accepting input."""
        return True

    def _setup_navigable(self) -> None:
        """Initialize the navigable border and hint.  Call from ``on_mount``."""
        self.add_class("navigable")
        self.border_subtitle = _NAV_HINT

    def deactivate(self) -> None:
        """Clear the navigation hint and notify ChatPane."""
        self.border_subtitle = None
        self.post_message(WidgetDeactivated(self))

    # ------------------------------------------------------------------
    # Focus / blur handlers — manage the subtitle hint
    # ------------------------------------------------------------------

    def on_focus(self) -> None:
        if self._is_navigable():
            self.border_subtitle = None

    def on_blur(self) -> None:
        if self._is_navigable():
            self.border_subtitle = _NAV_HINT

    def on_descendant_focus(self, event) -> None:
        if self._is_navigable():
            self.border_subtitle = None

    def on_descendant_blur(self, event) -> None:
        if self._is_navigable():
            self.border_subtitle = _NAV_HINT
