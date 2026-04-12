"""ResourceManager — tracks loaded resource state and computes diffs for the agent session."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from rhizome.logs import get_logger

_log = get_logger("resources.manager")


# ---------------------------------------------------------------------------
# State representation
# ---------------------------------------------------------------------------

class LoadMode(enum.Enum):
    """How a resource or section is loaded for the agent."""

    LOADED = "loaded"
    CONTEXT_STUFFED = "context_stuffed"


@dataclass(frozen=True)
class ResourceLoadState:
    """Load state for a single resource.

    ``root_state`` applies to the resource node itself (used for resources
    without extracted sections, or when the user toggles the resource as
    a whole).

    ``sections`` maps section IDs to their individual load modes.
    """

    root_state: LoadMode | None = None
    sections: dict[int, LoadMode] = field(default_factory=dict)

    @property
    def is_unloaded(self) -> bool:
        return self.root_state is None and not self.sections

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ResourceLoadState):
            return NotImplemented
        return self.root_state == other.root_state and self.sections == other.sections

    def __hash__(self) -> int:
        return hash((self.root_state, tuple(sorted(self.sections.items()))))


_EMPTY = ResourceLoadState()


def _fmt_state(state: ResourceLoadState) -> str:
    if state.is_unloaded:
        return "unloaded"
    parts = []
    if state.root_state is not None:
        parts.append(f"root={state.root_state.value}")
    if state.sections:
        sec_parts = [f"{sid}:{mode.value}" for sid, mode in sorted(state.sections.items())]
        parts.append(f"sections=[{', '.join(sec_parts)}]")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Diff types
# ---------------------------------------------------------------------------

class ResourceAction(enum.Enum):
    CONTEXT_STUFF = "context_stuff"
    UN_CONTEXT_STUFF = "un_context_stuff"
    LOAD = "load"
    UNLOAD = "unload"


@dataclass(frozen=True)
class ResourceChange:
    """A single state change for a resource or section.

    ``section_id`` is ``None`` for resource-level changes.
    """

    resource_id: int
    section_id: int | None
    action: ResourceAction


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ResourceManager:
    """Tracks per-resource load state and provides net diffs to the agent session.

    The ResourceLoader sends its full state snapshot on every change.
    The manager stores this as ``_next`` and only computes diffs at
    consumption time (when the agent session calls ``consume()``),
    comparing ``_next`` against ``_current`` (the last consumed state).
    """

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory
        self._current: dict[int, ResourceLoadState] = {}
        self._next: dict[int, ResourceLoadState] = {}
        self._embedding_in_progress: set[int] = set()

    # ------------------------------------------------------------------
    # State updates (called by the UI layer)
    # ------------------------------------------------------------------

    def set_state(self, state: dict[int, ResourceLoadState]) -> None:
        """Replace the next state wholesale with a snapshot from the loader."""
        old_next = self._next
        self._next = {rid: s for rid, s in state.items() if not s.is_unloaded}
        if self._next != old_next:
            _log.debug(
                "State updated: %s",
                ", ".join(f"r{rid}: {_fmt_state(s)}" for rid, s in sorted(self._next.items())) or "(empty)",
            )

    # ------------------------------------------------------------------
    # Embedding lifecycle
    # ------------------------------------------------------------------

    def is_embedding_in_progress(self, resource_id: int) -> bool:
        """True if an embedding computation is in-flight for this resource."""
        return resource_id in self._embedding_in_progress

    async def ensure_embedded(self, resource_id: int) -> bool:
        """Check for embeddings and compute them if missing.

        Returns ``True`` on success (embeddings now exist), ``False`` on
        failure (API error, missing raw_text, etc.).

        The caller is responsible for running this as an async task or
        Textual worker.
        """
        from rhizome.resources.embeddings import has_embeddings, compute_embeddings

        self._embedding_in_progress.add(resource_id)
        try:
            if await has_embeddings(self._session_factory, resource_id):
                _log.info("Resource %d already has embeddings", resource_id)
                return True

            _log.info("Computing embeddings for resource %d ...", resource_id)
            await compute_embeddings(self._session_factory, resource_id)
            _log.info("Embeddings complete for resource %d", resource_id)
            return True
        except Exception:
            _log.exception("Embedding failed for resource %d", resource_id)
            return False
        finally:
            self._embedding_in_progress.discard(resource_id)

    # ------------------------------------------------------------------
    # Diff computation
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_resource(
        resource_id: int,
        old: ResourceLoadState,
        new: ResourceLoadState,
    ) -> list[ResourceChange]:
        """Compute changes between two states for a single resource."""
        changes: list[ResourceChange] = []

        # Root state diff
        if old.root_state != new.root_state:
            if old.root_state is not None and new.root_state is None:
                # Was loaded/stuffed, now unloaded
                action = (ResourceAction.UN_CONTEXT_STUFF
                          if old.root_state == LoadMode.CONTEXT_STUFFED
                          else ResourceAction.UNLOAD)
                changes.append(ResourceChange(resource_id, None, action))
            elif new.root_state is not None and old.root_state is None:
                # Was unloaded, now loaded/stuffed
                action = (ResourceAction.CONTEXT_STUFF
                          if new.root_state == LoadMode.CONTEXT_STUFFED
                          else ResourceAction.LOAD)
                changes.append(ResourceChange(resource_id, None, action))
            else:
                # Mode changed (loaded <-> context_stuffed)
                # Emit unload-old then load-new
                old_action = (ResourceAction.UN_CONTEXT_STUFF
                              if old.root_state == LoadMode.CONTEXT_STUFFED
                              else ResourceAction.UNLOAD)
                new_action = (ResourceAction.CONTEXT_STUFF
                              if new.root_state == LoadMode.CONTEXT_STUFFED
                              else ResourceAction.LOAD)
                changes.append(ResourceChange(resource_id, None, old_action))
                changes.append(ResourceChange(resource_id, None, new_action))

        # Section diffs
        all_section_ids = set(old.sections) | set(new.sections)
        for sid in sorted(all_section_ids):
            old_mode = old.sections.get(sid)
            new_mode = new.sections.get(sid)
            if old_mode == new_mode:
                continue
            if old_mode is not None and new_mode is None:
                action = (ResourceAction.UN_CONTEXT_STUFF
                          if old_mode == LoadMode.CONTEXT_STUFFED
                          else ResourceAction.UNLOAD)
                changes.append(ResourceChange(resource_id, sid, action))
            elif new_mode is not None and old_mode is None:
                action = (ResourceAction.CONTEXT_STUFF
                          if new_mode == LoadMode.CONTEXT_STUFFED
                          else ResourceAction.LOAD)
                changes.append(ResourceChange(resource_id, sid, action))
            else:
                old_action = (ResourceAction.UN_CONTEXT_STUFF
                              if old_mode == LoadMode.CONTEXT_STUFFED
                              else ResourceAction.UNLOAD)
                new_action = (ResourceAction.CONTEXT_STUFF
                              if new_mode == LoadMode.CONTEXT_STUFFED
                              else ResourceAction.LOAD)
                changes.append(ResourceChange(resource_id, sid, old_action))
                changes.append(ResourceChange(resource_id, sid, new_action))

        return changes

    def _compute_diff(self) -> list[ResourceChange]:
        """Compute the net diff between current (consumed) and next state."""
        changes: list[ResourceChange] = []
        all_ids = set(self._current) | set(self._next)
        for rid in sorted(all_ids):
            old = self._current.get(rid, _EMPTY)
            new = self._next.get(rid, _EMPTY)
            if old != new:
                changes.extend(self._diff_resource(rid, old, new))
        return changes

    # ------------------------------------------------------------------
    # Consumption (called by AgentSession.stream)
    # ------------------------------------------------------------------

    def consume(self) -> list[ResourceChange]:
        """Return the net diff since the last ``consume()`` and freeze next as current.

        After this call, current equals next, so a subsequent ``consume()``
        with no intervening state updates returns an empty list.
        """
        diff = self._compute_diff()
        self._current = {rid: s for rid, s in self._next.items()}
        if diff:
            _log.info(
                "Consumed %d change(s): %s",
                len(diff),
                ", ".join(
                    f"r{c.resource_id}{f'.s{c.section_id}' if c.section_id is not None else ''}:{c.action.value}"
                    for c in diff
                ),
            )
        else:
            _log.debug("Consumed with no pending changes")
        return diff
