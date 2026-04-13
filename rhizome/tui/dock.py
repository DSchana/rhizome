"""Dock area utilities for the TUI.

Provides typed dock area containers and mixins for dockable widgets.

Layout convention:
- ``HorizontalDockArea`` is a side panel (left/right) — widgets inside
  arrange themselves **vertically**.
- ``VerticalDockArea`` is a top/bottom panel — widgets inside arrange
  themselves **horizontally**.
"""

from __future__ import annotations
from typing import Sequence

from textual.containers import Container
from textual.css.query import NoMatches
from textual.widget import Widget

from rhizome.tui.types import Arrangement


_DOCK_HIDDEN_CLASS = "--dock-empty"


class DockArea(Container):
    """Base class for dock area containers.

    Automatically hides itself (via ``--dock-empty`` CSS class) when it
    has no children, and shows itself when children are mounted.
    """

    DEFAULT_CSS = """
    DockArea.--dock-empty {
        display: none;
    }
    """

    def __init__(
        self,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        markup: bool = True,
    ) -> None:
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
            markup=markup,
        )

        if not children:
            self.add_class(_DOCK_HIDDEN_CLASS)

    async def mount(self, *widgets, **kwargs) -> None:
        """Mount children and show the dock area."""
        await super().mount(*widgets, **kwargs)
        if self.children:
            self.remove_class(_DOCK_HIDDEN_CLASS)

    def _check_empty(self) -> None:
        """Hide the dock area if it has no children."""
        if not self.children:
            self.add_class(_DOCK_HIDDEN_CLASS)

    def show(self) -> None:
        """Explicitly show this dock area."""
        self.remove_class(_DOCK_HIDDEN_CLASS)

    def hide(self) -> None:
        """Explicitly hide this dock area (widget stays mounted)."""
        self.add_class(_DOCK_HIDDEN_CLASS)

    @property
    def visible(self) -> bool:
        """True if the dock area is not hidden."""
        return not self.has_class(_DOCK_HIDDEN_CLASS)


class HorizontalDockArea(DockArea):
    """A dock area on the left or right side of the layout.

    Widgets docked here should arrange themselves vertically.
    """
    pass


class VerticalDockArea(DockArea):
    """A dock area on the top or bottom of the layout.

    Widgets docked here should arrange themselves horizontally.
    """
    pass


class DockableWidgetMixin:
    """Mixin for widgets that can be docked in a ``DockArea``.

    Provides ``docked_to()`` to query the ancestor dock area, and
    ``dock_arrangement`` to infer layout from the dock area type.
    """

    def docked_to(self: Widget) -> DockArea | None:
        """Return the ancestor ``DockArea``, or ``None`` if not docked."""
        try:
            return self.query_ancestor(DockArea)
        except NoMatches:
            return None

    @property
    def dock_arrangement(self: Widget) -> Arrangement:
        """Infer arrangement from the dock area type.

        Returns ``VERTICAL`` for ``HorizontalDockArea`` (side panels),
        ``HORIZONTAL`` for ``VerticalDockArea`` (top/bottom panels),
        and ``HORIZONTAL`` as the default if not docked.
        """
        dock = self.docked_to()
        if isinstance(dock, HorizontalDockArea):
            return Arrangement.VERTICAL
        return Arrangement.HORIZONTAL


class DockContainerMixin:
    """Mixin for widgets that contain dock areas.

    Provides helpers for mounting/moving widgets between dock areas
    and controlling dock area visibility.
    """

    async def mount_to_dock_area(
        self: Widget,
        widget: Widget,
        dock_id: str,
        *,
        before: int | str | Widget | None = None,
        after: int | str | Widget | None = None,
    ) -> None:
        """Move a widget to a dock area, removing it from its current parent.

        If the widget is already mounted, it is removed first.  The source
        dock area auto-hides if it becomes empty.  The target dock area is
        shown automatically by ``DockArea.mount``.
        """
        if widget.parent is not None:
            old_parent = widget.parent
            await widget.remove()
            if isinstance(old_parent, DockArea):
                old_parent._check_empty()

        dock_area = self.query_one(f"#{dock_id}", DockArea)
        await dock_area.mount(widget, before=before, after=after)

    def get_dock_area(self: Widget, dock_id: str) -> DockArea:
        """Return a dock area by ID."""
        return self.query_one(f"#{dock_id}", DockArea)
