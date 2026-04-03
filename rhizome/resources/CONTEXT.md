# rhizome/resources/

Resource processing services — higher-level operations on document resources that go beyond simple CRUD.

## Subpackages

- **`extraction/`** — Automatic section/subsection discovery pipeline. Combines format-specific heuristic extraction with LLM-based refinement to produce hierarchical section trees from documents.

## Relationship to Other Modules

- **`rhizome/db/`** — This package does NOT handle persistence. Database models (`Resource`, `ResourceSection`, `ResourceChunk`) and operations live in `rhizome/db/`.
- **`rhizome/agent/tools/`** — Agent tools call into this package to trigger section detection. This package has no dependency on the agent layer.
