"""ResourceManager — tracks loaded resource state and computes diffs for the agent session."""

from __future__ import annotations

import enum
from dataclasses import dataclass

from rhizome.logs import get_logger

_log = get_logger("resources.manager")


# ---------------------------------------------------------------------------
# Per-resource state (two independent axes)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResourceState:
    """Snapshot of a single resource's load state across two axes."""

    in_vector_store: bool = False
    context_stuffed: bool = False

    @property
    def is_unloaded(self) -> bool:
        return not self.in_vector_store and not self.context_stuffed


_EMPTY = ResourceState()


def _fmt_state(state: ResourceState) -> str:
    if state.is_unloaded:
        return "unloaded"
    parts = []
    if state.in_vector_store:
        parts.append("vector")
    if state.context_stuffed:
        parts.append("context")
    return "+".join(parts)


# ---------------------------------------------------------------------------
# Diff types
# ---------------------------------------------------------------------------

class ResourceAction(enum.Enum):
    CONTEXT_STUFF = "context_stuff"
    UN_CONTEXT_STUFF = "un_context_stuff"
    VECTOR_LOAD = "vector_load"
    VECTOR_UNLOAD = "vector_unload"


@dataclass(frozen=True)
class ResourceChange:
    resource_id: int
    action: ResourceAction


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ResourceManager:
    """Tracks per-resource load state and provides net diffs to the agent session.

    The two axes per resource are:
        - **in_vector_store**: whether the resource's embeddings are active
          for retrieval.
        - **context_stuffed**: whether the resource's full text is injected
          into the conversation context.

    These axes are independent — context-stuffing does not affect vector
    store state and vice-versa.

    Usage:
        1. ``ResourceLoader`` (or its parent) calls
           ``notify_load_state_changed()`` whenever the user toggles a
           resource in the UI.
        2. ``AgentSession.stream()`` calls ``consume()`` at the start of
           each turn to obtain the net diff since the previous call and
           freeze the current state.
    """

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory
        self._current: dict[int, ResourceState] = {}
        self._frozen: dict[int, ResourceState] | None = None
        self._embedding_in_progress: set[int] = set()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_state(self, resource_id: int) -> ResourceState:
        return self._current.get(resource_id, _EMPTY)

    @property
    def current_snapshot(self) -> dict[int, ResourceState]:
        """Read-only copy of the current state."""
        return dict(self._current)

    # ------------------------------------------------------------------
    # Mutations (called by the UI layer)
    # ------------------------------------------------------------------

    def _put_state(self, resource_id: int, state: ResourceState) -> None:
        old = self._current.get(resource_id, _EMPTY)
        if state.is_unloaded:
            self._current.pop(resource_id, None)
        else:
            self._current[resource_id] = state
        if state != old:
            _log.info(
                "Resource %d: %s → %s",
                resource_id, _fmt_state(old), _fmt_state(state),
            )

    def set_context_stuffed(self, resource_id: int, stuffed: bool) -> None:
        old = self.get_state(resource_id)
        self._put_state(resource_id, ResourceState(
            in_vector_store=old.in_vector_store,
            context_stuffed=stuffed,
        ))

    def set_vector_loaded(self, resource_id: int, loaded: bool) -> None:
        old = self.get_state(resource_id)
        self._put_state(resource_id, ResourceState(
            in_vector_store=loaded,
            context_stuffed=old.context_stuffed,
        ))

    def full_unload(self, resource_id: int) -> None:
        """Set both axes to ``False``."""
        self._put_state(resource_id, _EMPTY)

    # ------------------------------------------------------------------
    # Embedding lifecycle
    # ------------------------------------------------------------------

    def is_embedding_in_progress(self, resource_id: int) -> bool:
        """True if an embedding computation is in-flight for this resource."""
        return resource_id in self._embedding_in_progress

    async def ensure_embedded(self, resource_id: int) -> bool:
        """Check for embeddings and compute them if missing.

        Returns ``True`` on success (embeddings now exist), ``False`` on
        failure (API error, missing raw_text, etc.).  On failure the
        vector-loaded state is reverted to ``False``.

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
            self.set_vector_loaded(resource_id, False)
            return False
        finally:
            self._embedding_in_progress.discard(resource_id)

    # ------------------------------------------------------------------
    # Diff computation
    # ------------------------------------------------------------------

    def _compute_diff(self) -> list[ResourceChange]:
        """Compute the net diff between frozen and current state."""
        frozen = self._frozen if self._frozen is not None else {}
        changes: list[ResourceChange] = []

        all_ids = set(self._current) | set(frozen)
        for rid in sorted(all_ids):
            old = frozen.get(rid, _EMPTY)
            new = self._current.get(rid, _EMPTY)

            if not old.context_stuffed and new.context_stuffed:
                changes.append(ResourceChange(rid, ResourceAction.CONTEXT_STUFF))
            elif old.context_stuffed and not new.context_stuffed:
                changes.append(ResourceChange(rid, ResourceAction.UN_CONTEXT_STUFF))

            if not old.in_vector_store and new.in_vector_store:
                changes.append(ResourceChange(rid, ResourceAction.VECTOR_LOAD))
            elif old.in_vector_store and not new.in_vector_store:
                changes.append(ResourceChange(rid, ResourceAction.VECTOR_UNLOAD))

        return changes

    # ------------------------------------------------------------------
    # Consumption (called by AgentSession.stream)
    # ------------------------------------------------------------------

    def consume(self) -> list[ResourceChange]:
        """Return the net diff since the last ``consume()`` and freeze current state.

        After this call, the frozen state equals the current state, so a
        subsequent ``consume()`` with no intervening mutations returns an
        empty list.
        """
        diff = self._compute_diff()
        # Freeze: deep-copy current (ResourceState is frozen, so dict copy suffices).
        self._frozen = dict(self._current)
        if diff:
            _log.info(
                "Consumed %d change(s): %s",
                len(diff),
                ", ".join(f"r{c.resource_id}:{c.action.value}" for c in diff),
            )
        else:
            _log.debug("Consumed with no pending changes")
        return diff
