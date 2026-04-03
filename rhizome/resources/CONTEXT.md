# rhizome/resources/

Resource processing services — higher-level operations on document resources that go beyond simple CRUD.

## Modules

- **manager.py** — `ResourceManager`: tracks per-resource load state on two independent axes (`in_vector_store`, `context_stuffed`) and computes net diffs between agent `stream()` calls. Created by `ChatPane` and shared between `AgentSession` (which calls `consume()` to drain changes) and `ResourceViewer` (which calls `notify_load_state_changed()` on user toggles). Exposes `set_context_stuffed()`, `set_vector_loaded()`, and `full_unload()` as mutation methods. The translation from `ResourceLoader` tri-state to two-axis calls lives in `ResourceViewer.on_resource_loader_state_changed()`. Exports `ResourceState`, `ResourceAction`, `ResourceChange`.

## Subpackages

- **`extraction/`** — Automatic section/subsection discovery pipeline. Combines format-specific heuristic extraction with LLM-based refinement to produce hierarchical section trees from documents.

## Relationship to Other Modules

- **`rhizome/db/`** — This package does NOT handle persistence. Database models (`Resource`, `ResourceSection`, `ResourceChunk`) and operations live in `rhizome/db/`.
- **`rhizome/agent/tools/`** — Agent tools call into this package to trigger section detection. This package has no dependency on the agent layer.
- **`rhizome/tui/widgets/`** — `ResourceViewer` translates `ResourceLoader` tri-state changes into `ResourceManager` two-axis calls. This package has no dependency on the TUI layer.
- **`rhizome/agent/session.py`** — `AgentSession` holds a `ResourceManager` reference and calls `consume()` at the start of each `stream()` invocation.
