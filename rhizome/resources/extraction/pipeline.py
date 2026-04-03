"""Format-agnostic LLM refinement pipeline for section detection.

Consumes an ``ExtractionResult`` from any ``DocumentExtractor`` and
produces a tree of confirmed ``Section`` objects via batched LLM calls
with early exit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from rhizome.resources.extraction.protocol import (
    DocumentExtractor,
    ExtractionResult,
    HeadingCandidate,
    Section,
)


# ── Structured output schemas ───────────────────────────────────────


class BatchDecision(BaseModel):
    """LLM decision for a single heading candidate."""

    accept: bool
    depth: int = 0
    title: str = ""
    reason: str = ""


class BatchResponse(BaseModel):
    """LLM response for a batch of heading candidates."""

    decisions: list[BatchDecision]


class CleanupSection(BaseModel):
    """A section entry in the cleanup response."""

    title: str
    depth: int
    page: int


class CleanupResponse(BaseModel):
    """LLM response for the tree cleanup pass."""

    sections: list[CleanupSection]
    changes: list[str] = Field(default_factory=list)


# ── Pipeline statistics ─────────────────────────────────────────────


@dataclass
class PipelineStats:
    """Aggregate statistics from a pipeline run.

    Token counts are optional because not all LLM providers report them.
    """

    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    batches_processed: int = 0
    batches_skipped: int = 0
    candidates_total: int = 0
    sections_accepted: int = 0

    @property
    def total_tokens(self) -> int | None:
        if self.total_input_tokens is None or self.total_output_tokens is None:
            return None
        return self.total_input_tokens + self.total_output_tokens


def _add_tokens(stats: PipelineStats, usage: dict) -> None:
    """Accumulate token counts from a langchain usage_metadata dict."""
    input_tok = usage.get("input_tokens")
    output_tok = usage.get("output_tokens")
    if input_tok is not None:
        stats.total_input_tokens = (stats.total_input_tokens or 0) + input_tok
    if output_tok is not None:
        stats.total_output_tokens = (stats.total_output_tokens or 0) + output_tok


# ── Tree building ───────────────────────────────────────────────────


def build_tree(flat_sections: list[Section]) -> list[Section]:
    """Build a nested tree from a flat list of sections in document order.

    Uses each section's ``depth`` to determine parent-child relationships:
    a section becomes a child of the most recent section with a smaller
    depth value.
    """
    ordered = sorted(flat_sections, key=lambda s: s.position_index)

    roots: list[Section] = []
    stack: list[Section] = []

    for section in ordered:
        while stack and stack[-1].depth >= section.depth:
            stack.pop()

        if stack:
            stack[-1].children.append(section)
        else:
            roots.append(section)

        stack.append(section)

    return roots


# ── Prompt formatting ───────────────────────────────────────────────

BATCH_SYSTEM_PROMPT = """\
You are a document structure analyzer. You receive batches of heading candidates \
extracted from a document via heuristics, along with context. Your job is to determine \
which candidates are real section/subsection headings and which are false positives \
(figure labels, chart text, page headers, table captions, bold terms, etc.).

For each candidate, decide:
1. accept: true if it's a real section/subsection heading, false otherwise
2. depth: nesting level (1 = top-level chapter/part, 2 = section, 3 = subsection, etc.)
3. title: the cleaned heading text — you may fix OCR artifacts and remove trailing page \
numbers, but ALWAYS preserve section numbering when it is present in the original text \
(e.g. "3.2 Methods" should stay "3.2 Methods", not just "Methods").

You will also receive the current section tree built from prior batches. Use it to:
- Reject duplicates of already-accepted sections
- Infer correct depth from the existing hierarchy (e.g., "3.2.1 ..." is depth 3 under "3.2")
- Maintain consistency in numbering schemes

For each candidate, provide a decision object with:
  accept (bool), depth (int), title (str), reason (str)
- For accepted candidates, "reason" can be empty.
- For rejected candidates, "reason" should explain why (e.g. "figure axis label", \
"duplicate of 3.2", "page header", "bold term in paragraph, not a heading").
  depth and title can be 0 and "" for rejected candidates.

Return decisions in the same order as the candidates."""


CLEANUP_SYSTEM_PROMPT = """\
You are a document structure editor. You receive a section tree extracted from a document \
and your job is to fix structural issues. The tree is represented as a flat list of \
sections, each with a title, depth, and page number.

Common issues to fix:
- Incorrect nesting: siblings incorrectly placed as children (e.g. items A, B, C, D \
at the same level where C and D got nested under B)
- Inconsistent depth: sections that should be at the same level have different depths
- Title cleanup: minor OCR artifacts, inconsistent formatting

Do NOT:
- Remove sections (the acceptance decision was already made)
- Add sections that aren't in the input
- Change page numbers

Return all sections in their original order with corrected depth/title where needed, \
plus a list of changes made (empty if none needed)."""


def _format_candidate(candidate: HeadingCandidate, index: int) -> str:
    """Format a single candidate with context for the LLM prompt."""
    lines = [f"  Candidate {index}:"]
    lines.append(f"    text: {candidate.text!r}")
    lines.append(f"    page: {candidate.page}")
    lines.append(f"    heuristic_score: {candidate.score:.1f}")
    lines.append(f"    detection_method: {candidate.source}")
    lines.append(f"    signals: {', '.join(candidate.signals)}")
    if candidate.context_before:
        lines.append(f"    context_before: {candidate.context_before!r}")
    if candidate.context_after:
        lines.append(f"    context_after: {candidate.context_after!r}")
    return "\n".join(lines)


def _format_accepted_tree(sections: list[Section]) -> str:
    """Format the running list of accepted sections for the prompt."""
    if not sections:
        return "(none yet)"
    return "\n".join(s.tree_str() for s in sections)


def _build_batch_prompt(
    batch: list[HeadingCandidate],
    accepted_tree: list[Section],
    doc_title: str | None,
) -> str:
    parts = []
    if doc_title:
        parts.append(f"Document: {doc_title}")
        parts.append("")

    parts.append("=== Accepted sections so far ===")
    parts.append(_format_accepted_tree(accepted_tree))
    parts.append("")

    parts.append(f"=== Candidates (batch of {len(batch)}) ===")
    for i, cand in enumerate(batch):
        parts.append(_format_candidate(cand, i))
        parts.append("")

    return "\n".join(parts)


def _build_cleanup_prompt(
    flat_sections: list[Section],
    doc_title: str | None,
) -> str:
    lines = []
    if doc_title:
        lines.append(f"Document: {doc_title}")
        lines.append("")
    lines.append(f"Section tree ({len(flat_sections)} sections):")
    for i, s in enumerate(flat_sections):
        indent = "  " * s.depth
        page_str = f" (p.{s.page})" if s.page is not None else ""
        lines.append(f"  [{i}] depth={s.depth}  {indent}{s.title}{page_str}")
    return "\n".join(lines)


# ── Batch processing ────────────────────────────────────────────────


@dataclass
class _BatchResult:
    new_sections: list[Section]
    input_tokens: int | None
    output_tokens: int | None


def _extract_usage(raw_message) -> tuple[int | None, int | None]:
    """Pull input/output token counts from a raw AIMessage, if available."""
    usage = getattr(raw_message, "usage_metadata", None) or {}
    return usage.get("input_tokens"), usage.get("output_tokens")


async def _process_batch(
    llm: BaseChatModel,
    batch: list[HeadingCandidate],
    accepted_tree: list[Section],
    doc_title: str | None,
) -> _BatchResult:
    """Send a batch of candidates to the LLM and return newly accepted sections."""
    structured_llm = llm.with_structured_output(BatchResponse, include_raw=True)

    user_prompt = _build_batch_prompt(batch, accepted_tree, doc_title)
    messages = [
        SystemMessage(content=BATCH_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    result = await structured_llm.ainvoke(messages)
    response: BatchResponse = result["parsed"]
    input_tokens, output_tokens = _extract_usage(result["raw"])

    decisions = response.decisions
    if len(decisions) != len(batch):
        # Truncate or pad — use what we got
        decisions = decisions[: len(batch)]

    new_sections: list[Section] = []
    for i, decision in enumerate(decisions):
        if not decision.accept:
            continue
        cand = batch[i]
        new_sections.append(Section(
            title=decision.title or cand.text.strip(),
            depth=decision.depth,
            page=cand.page,
            position_index=cand.position_index,
            start_offset=cand.text_offset,
        ))

    return _BatchResult(new_sections, input_tokens, output_tokens)


# ── Tree cleanup ────────────────────────────────────────────────────


def _flatten_tree(tree: list[Section]) -> list[Section]:
    """Flatten a nested section tree into document order."""
    flat: list[Section] = []

    def walk(sections: list[Section]) -> None:
        for s in sections:
            flat.append(s)
            walk(s.children)

    walk(tree)
    return flat


async def _cleanup_tree(
    llm: BaseChatModel,
    tree: list[Section],
    doc_title: str | None,
    stats: PipelineStats,
) -> list[Section]:
    """Run a single LLM pass to fix structural issues in the final tree."""
    flat = _flatten_tree(tree)
    if not flat:
        return tree

    structured_llm = llm.with_structured_output(CleanupResponse, include_raw=True)

    user_prompt = _build_cleanup_prompt(flat, doc_title)
    messages = [
        SystemMessage(content=CLEANUP_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    result = await structured_llm.ainvoke(messages)
    response: CleanupResponse = result["parsed"]
    input_tokens, output_tokens = _extract_usage(result["raw"])

    _add_tokens(stats, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    })
    stats.batches_processed += 1

    if len(response.sections) != len(flat):
        # Length mismatch — return tree unchanged
        return tree

    # Apply updates
    for i, update in enumerate(response.sections):
        flat[i].title = update.title
        flat[i].depth = update.depth
        flat[i].children = []

    return build_tree(flat)


# ── Main pipeline ───────────────────────────────────────────────────


async def detect_sections(
    extraction: ExtractionResult,
    llm: BaseChatModel,
    *,
    batch_size: int = 15,
) -> tuple[list[Section], PipelineStats]:
    """Run LLM refinement on extracted heading candidates.

    This is format-agnostic: it consumes the candidate list and context
    from any ``DocumentExtractor``, not the original document.

    Args:
        extraction: Result from a ``DocumentExtractor``.
        llm: A langchain chat model instance (any provider).
        batch_size: Number of candidates per LLM batch.

    Returns:
        A tuple of (nested section tree, pipeline statistics).
    """
    stats = PipelineStats(candidates_total=len(extraction.candidates))

    candidates = sorted(extraction.candidates, key=lambda c: c.score, reverse=True)
    if not candidates:
        return [], stats

    # Process batches in score-descending order with early exit
    all_accepted: list[Section] = []
    accepted_tree: list[Section] = []
    consecutive_empty = 0

    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start : batch_start + batch_size]

        result = await _process_batch(
            llm, batch, accepted_tree, extraction.doc_title,
        )

        # Accumulate tokens
        if result.input_tokens is not None or result.output_tokens is not None:
            _add_tokens(stats, {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            })
        stats.batches_processed += 1

        all_accepted.extend(result.new_sections)
        stats.sections_accepted = len(all_accepted)

        # Rebuild the running tree for context in the next batch
        accepted_tree = build_tree([
            Section(
                title=s.title,
                depth=s.depth,
                page=s.page,
                position_index=s.position_index,
                start_offset=s.start_offset,
            )
            for s in all_accepted
        ])

        # Early exit: 2 consecutive batches with no new sections
        if not result.new_sections:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                total_batches = (len(candidates) + batch_size - 1) // batch_size
                stats.batches_skipped = total_batches - (batch_start // batch_size + 1)
                break
        else:
            consecutive_empty = 0

    # Build final tree from all accepted sections
    # Clear children from the flat list before rebuilding
    for s in all_accepted:
        s.children = []
    tree = build_tree(all_accepted)

    # Cleanup pass
    if tree:
        tree = await _cleanup_tree(llm, tree, extraction.doc_title, stats)

    return tree, stats


# ── Extractor registry ──────────────────────────────────────────────

_EXTRACTOR_REGISTRY: dict[str, type[DocumentExtractor]] = {}


def register_extractor(source_type: str, cls: type[DocumentExtractor]) -> None:
    """Register a ``DocumentExtractor`` class for a source type."""
    _EXTRACTOR_REGISTRY[source_type] = cls


def get_extractor(source_type: str) -> DocumentExtractor:
    """Instantiate the registered extractor for a source type.

    Raises ``ValueError`` if no extractor is registered for the type.
    """
    cls = _EXTRACTOR_REGISTRY.get(source_type)
    if cls is None:
        available = ", ".join(sorted(_EXTRACTOR_REGISTRY)) or "(none)"
        raise ValueError(
            f"No extractor registered for source type {source_type!r}. "
            f"Available: {available}"
        )
    return cls()


def _register_builtins() -> None:
    from rhizome.resources.extraction.pdf import PdfExtractor

    register_extractor("pdf", PdfExtractor)


_register_builtins()


# ── Top-level API ───────────────────────────────────────────────────


async def process_document(
    source: bytes,
    source_type: str,
    llm: BaseChatModel,
    *,
    batch_size: int = 15,
) -> tuple[list[Section], ExtractionResult, PipelineStats]:
    """Extract and detect sections from a document in one call.

    Args:
        source: Raw document bytes.
        source_type: Format identifier (e.g. ``"pdf"``).  Must have a
            registered ``DocumentExtractor``.
        llm: A langchain chat model instance (any provider).
        batch_size: Number of candidates per LLM batch.

    Returns:
        A tuple of (section tree, extraction result, pipeline stats).
    """
    extractor = get_extractor(source_type)
    extraction = extractor.extract(source)
    tree, stats = await detect_sections(extraction, llm, batch_size=batch_size)
    return tree, extraction, stats
