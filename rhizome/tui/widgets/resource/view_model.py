"""View models for the ResourceViewer widget family.

These classes hold the persistent state that survives widget destroy/recreate
cycles (e.g. when changing dock position).  Each widget reads from its view
model on compose/mount and writes back on user interaction.

Hierarchy::

    ResourceViewerViewModel
    ├── .resource_list   → ResourceListViewModel
    ├── .resource_linker → ResourceLinkerViewModel
    └── .resource_loader → ResourceLoaderViewModel
"""

from __future__ import annotations

import enum

from rhizome.db import Resource, Topic



class LoadState(enum.Enum):
    """Load state for a resource or section."""

    UNLOADED = "unloaded"
    DEFAULT = "default"          # loaded per resource's loading_preference
    CONTEXT_STUFFED = "context"  # override: context-stuffed directly
    PENDING = "pending"          # embedding in progress — locked, shows spinner


# ======================================================================
# Sub-widget view models
# ======================================================================

class ResourceListViewModel:
    """State for the ResourceList widget."""

    def __init__(self) -> None:
        self.resources: list[Resource] = []
        self.cursor: int = 0
        self.show_ids: bool = False


class ResourceLinkerViewModel:
    """State for the ResourceLinker widget."""

    def __init__(self) -> None:
        self.resources: list[Resource] = []
        self.linked_ids: set[int] = set()
        self.cursor: int = 0
        self.show_ids: bool = False


class ResourceLoaderViewModel:
    """State for the ResourceLoader widget.

    ``states`` maps ``(kind, id)`` tuples — where *kind* is ``"resource"``
    or ``"section"`` — to their current :class:`LoadState`.
    """

    def __init__(self) -> None:
        self.resources: list[Resource] = []
        self.states: dict[tuple[str, int], LoadState] = {}
        self.show_ids: bool = False
        self.spinner_frame: int = 0


# ======================================================================
# Top-level view model
# ======================================================================


class ResourceViewMode(enum.IntEnum):
    """Which resource view is active in the ResourceViewer panel."""
    TOPIC_RESOURCES = 0
    LINK_RESOURCES = 1
    LOAD_RESOURCES = 2


class ResourceViewerViewModel:
    """Persistent state for the ResourceViewer panel.

    Created once by ChatPane and handed to each new ResourceViewer
    instance.  Survives widget destruction so caches, active topic,
    and load states are preserved across dock-position changes.
    """

    def __init__(self) -> None:
        # -- View mode & display ------------------------------------------
        self.view_mode: ResourceViewMode = ResourceViewMode.TOPIC_RESOURCES
        self.show_ids: bool = False

        # -- Active / cursor topic ----------------------------------------
        self.active_topic: Topic | None = None
        self.active_topic_path: list[str] = []
        self.current_topic_id: int | None = None

        # -- Caches -------------------------------------------------------
        self.resource_cache: dict[int, list[Resource]] = {}
        self.loader_resource_cache: dict[int, list[Resource]] = {}
        self.resource_cursor_cache: dict[int, int] = {}
        self.all_resources: list[Resource] | None = None
        self.linked_ids_cache: dict[int, set[int]] = {}

        # -- Composed sub-view-models -------------------------------------
        self.resource_list = ResourceListViewModel()
        self.resource_linker = ResourceLinkerViewModel()
        self.resource_loader = ResourceLoaderViewModel()
