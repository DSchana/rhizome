"""Format-agnostic LLM refinement pipeline for section detection.

Consumes an ``ExtractionResult`` from any ``DocumentExtractor`` and
produces a tree of confirmed ``Section`` objects via batched LLM calls
with early exit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from rhizome.logs import get_logger
from rhizome.resources.extraction.protocol import (
    DocumentExtractor,
    ExtractionResult,
    HeadingCandidate,
    Section,
)

_log = get_logger("resources.extraction.pipeline")


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


# ── Token cost estimation ──────────────────────────────────────────


def _next_power_of_2(n: int) -> int:
    """Return the smallest power of 2 >= *n* (minimum 1)."""
    p = 1
    while p < n:
        p <<= 1
    return p


def estimate_extraction_tokens(document_tokens: int) -> int:
    """Rough estimate of total tokens consumed by the extraction pipeline.

    Based on a linear interpolation of observed token usage across a small
    and large document.  This is intentionally approximate — the actual
    cost depends on candidate density, batch count, and LLM verbosity.
    """
    return max(document_tokens, int(7 * document_tokens - 90_000))


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
    response: BatchResponse | None = result["parsed"]
    input_tokens, output_tokens = _extract_usage(result["raw"])

    if response is None:
        _log.error(
            "Batch failed to parse structured output — skipping batch. "
            "Full result: %s",
            repr(result),
        )
        return _BatchResult([], input_tokens, output_tokens)

    decisions = response.decisions
    if len(decisions) != len(batch):
        # Truncate or pad — use what we got
        decisions = decisions[: len(batch)]

    new_sections: list[Section] = []
    rejections: list[tuple[HeadingCandidate, str]] = []
    for i, decision in enumerate(decisions):
        if not decision.accept:
            rejections.append((batch[i], decision.reason))
            continue
        cand = batch[i]
        new_sections.append(Section(
            title=decision.title or cand.text.strip(),
            depth=decision.depth,
            page=cand.page,
            position_index=cand.position_index,
            start_offset=cand.text_offset,
        ))

    for s in new_sections:
        _log.debug('     + depth=%d  "%s" (p.%s)', s.depth, s.title, s.page)
    for cand, reason in rejections:
        _log.debug(
            '     - "%s" (p.%s, score=%.1f): %s',
            cand.text.strip(), cand.page, cand.score, reason,
        )

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

    user_prompt = _build_cleanup_prompt(flat, doc_title)
    messages = [
        SystemMessage(content=CLEANUP_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    # Estimate input tokens and set max_tokens to the next power of 2.
    prompt_chars = sum(len(m.content) for m in messages)
    estimated_input = prompt_chars // 4
    max_tokens = _next_power_of_2(estimated_input)
    _log.debug(
        "Cleanup: ~%d input tokens estimated, setting max_tokens=%d",
        estimated_input, max_tokens,
    )

    structured_llm = llm.bind(max_tokens=max_tokens).with_structured_output(
        CleanupResponse, include_raw=True,
    )
    result = await structured_llm.ainvoke(messages)
    response: CleanupResponse | None = result["parsed"]
    input_tokens, output_tokens = _extract_usage(result["raw"])

    _add_tokens(stats, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    })
    stats.batches_processed += 1

    if response is None:
        _log.error(
            "Cleanup pass failed to parse structured output — returning tree unchanged. "
            "Full result: %s",
            repr(result),
        )
        return tree

    if len(response.sections) != len(flat):
        _log.warning(
            "Cleanup returned %d sections, expected %d — skipping",
            len(response.sections), len(flat),
        )
        return tree

    # Apply updates
    for i, update in enumerate(response.sections):
        flat[i].title = update.title
        flat[i].depth = update.depth
        flat[i].children = []

    if response.changes:
        for change in response.changes:
            _log.info("  * %s", change)
    else:
        _log.info("  (no changes)")

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
        _log.info("No heading candidates found")
        return [], stats

    total_batches = (len(candidates) + batch_size - 1) // batch_size
    _log.info(
        "Found %d heading candidates, processing in up to %d batches of %d",
        len(candidates), total_batches, batch_size,
    )

    # Process batches in score-descending order with early exit
    pipeline_start = time.monotonic()
    all_accepted: list[Section] = []
    accepted_tree: list[Section] = []
    consecutive_empty = 0

    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        score_range = f"{batch[-1].score:.1f}-{batch[0].score:.1f}"

        _log.info(
            "Batch %d/%d: %d candidates (scores %s)",
            batch_num, total_batches, len(batch), score_range,
        )

        t0 = time.monotonic()
        result = await _process_batch(
            llm, batch, accepted_tree, extraction.doc_title,
        )
        elapsed = time.monotonic() - t0

        # Accumulate tokens
        if result.input_tokens is not None or result.output_tokens is not None:
            _add_tokens(stats, {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            })
        stats.batches_processed += 1

        accepted = len(result.new_sections)
        rejected = len(batch) - accepted
        tok_str = ""
        if result.input_tokens is not None:
            tok_str = f", {result.input_tokens} in / {result.output_tokens} out"
        _log.info(
            "  -> %d accepted, %d rejected  [%.1fs%s]",
            accepted, rejected, elapsed, tok_str,
        )

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
                stats.batches_skipped = total_batches - batch_num
                _log.info(
                    "Early exit: 2 consecutive empty batches. Skipping %d remaining batch(es).",
                    stats.batches_skipped,
                )
                break
        else:
            consecutive_empty = 0

    pipeline_elapsed = time.monotonic() - pipeline_start

    # Pipeline summary
    tok_summary = ""
    if stats.total_tokens is not None:
        tok_summary = f", {stats.total_tokens:,} tokens"
    batches_summary = f"{stats.batches_processed} processed"
    if stats.batches_skipped:
        batches_summary += f", {stats.batches_skipped} skipped"
    _log.info(
        "Pipeline summary: %d candidates, %s, %d sections accepted%s [%.1fs]",
        stats.candidates_total, batches_summary, stats.sections_accepted,
        tok_summary, pipeline_elapsed,
    )

    # Build final tree from all accepted sections
    # Clear children from the flat list before rebuilding
    for s in all_accepted:
        s.children = []
    tree = build_tree(all_accepted)

    # Cleanup pass
    if tree:
        _log.info("Running cleanup pass on final tree...")
        t0 = time.monotonic()
        tree = await _cleanup_tree(llm, tree, extraction.doc_title, stats)
        elapsed = time.monotonic() - t0
        tok_str = ""
        if stats.total_input_tokens is not None:
            tok_str = f", {stats.total_input_tokens} in / {stats.total_output_tokens} out"
        _log.info("  Cleanup done [%.1fs%s]", elapsed, tok_str)

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


async def extract_document_subsections(
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

    _log.info(
        "Extracted %d candidates from %s document (%s pages)",
        len(extraction.candidates),
        source_type,
        extraction.page_count or "?",
    )
    meta = extraction.metadata
    if meta.get("body_font_name"):
        _log.info(
            "Body font: %s @ %.1fpt, color: 0x%06X",
            meta["body_font_name"],
            meta.get("body_font_size", 0),
            meta.get("body_color", 0),
        )

    tree, stats = await detect_sections(extraction, llm, batch_size=batch_size)
    return tree, extraction, stats
