"""PDF document extractor using pymupdf (fitz).

Implements the ``DocumentExtractor`` protocol for PDF files.  Heuristic
heading detection uses three strategies (isolated block, leading-span,
contiguous non-body lines) with scoring based on font size, weight, color,
numbering patterns, and vertical layout.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import fitz  # pymupdf

from rhizome.resources.extraction.protocol import (
    DocumentExtractor,
    ExtractionResult,
    HeadingCandidate,
)


# ── Internal data structures ────────────────────────────────────────


@dataclass
class _SpanInfo:
    """A contiguous run of text with uniform formatting."""

    text: str
    font_name: str
    font_size: float
    is_bold: bool
    is_italic: bool
    color: int  # sRGB packed int
    origin: tuple[float, float]  # (x, y) position on page


@dataclass
class _LineInfo:
    """A single line composed of spans."""

    spans: list[_SpanInfo] = field(default_factory=list)
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def dominant_font_size(self) -> float:
        if not self.spans:
            return 0
        return max(self.spans, key=lambda s: len(s.text)).font_size

    @property
    def is_bold(self) -> bool:
        return any(s.is_bold for s in self.spans)


@dataclass
class _BlockInfo:
    """A text block (paragraph-level grouping from pymupdf)."""

    lines: list[_LineInfo] = field(default_factory=list)
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    page_num: int = 0

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)


@dataclass
class _DocStats:
    """Aggregate font statistics computed once over the whole document."""

    body_font_size: float
    body_font_name: str
    body_color: int
    page_count: int
    page_height: float
    repeated_page_strings: set[str] = field(default_factory=set)
    figure_fonts: set[str] = field(default_factory=set)


# ── Internal heading candidate (pre-conversion) ────────────────────


@dataclass
class _RawCandidate:
    """Heading candidate before conversion to the protocol type."""

    text: str
    page_num: int
    block_index: int
    font_name: str
    font_size: float
    signals: list[str]
    score: float
    source: str


# ── Extraction helpers ──────────────────────────────────────────────


def _extract_blocks(doc: fitz.Document) -> list[_BlockInfo]:
    """Extract all text blocks with full span-level metadata."""
    blocks: list[_BlockInfo] = []

    for page_num, page in enumerate(doc):
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue

            block_info = _BlockInfo(
                bbox=tuple(block["bbox"]),
                page_num=page_num,
            )

            for line in block.get("lines", []):
                line_info = _LineInfo(bbox=tuple(line["bbox"]))

                for span in line.get("spans", []):
                    flags = span.get("flags", 0)
                    line_info.spans.append(_SpanInfo(
                        text=span["text"],
                        font_name=span["font"],
                        font_size=round(span["size"], 2),
                        is_bold=bool(flags & (1 << 4)),
                        is_italic=bool(flags & (1 << 1)),
                        color=span.get("color", 0),
                        origin=tuple(span.get("origin", (0, 0))),
                    ))

                if line_info.spans:
                    block_info.lines.append(line_info)

            if block_info.lines:
                blocks.append(block_info)

    return blocks


def _compute_doc_stats(doc: fitz.Document, blocks: list[_BlockInfo]) -> _DocStats:
    """Compute body font, body color, page dimensions, and detect repeated headers/footers."""
    page_count = len(doc)

    font_char_counts: Counter[tuple[str, float]] = Counter()
    color_char_counts: Counter[int] = Counter()
    for block in blocks:
        for line in block.lines:
            for span in line.spans:
                key = (span.font_name, round(span.font_size, 1))
                char_len = len(span.text)
                font_char_counts[key] += char_len
                color_char_counts[span.color] += char_len

    if not font_char_counts:
        body_font_name, body_font_size = "unknown", 12.0
    else:
        (body_font_name, body_font_size) = font_char_counts.most_common(1)[0][0]

    body_color = color_char_counts.most_common(1)[0][0] if color_char_counts else 0

    heights = sorted(page.rect.height for page in doc)
    page_height = heights[len(heights) // 2] if heights else 792.0

    # Repeated page strings (headers/footers)
    page_strings: dict[str, set[int]] = {}
    for block in blocks:
        text = block.text.strip()
        if not text or len(text) > 60:
            continue
        if len(block.lines) > 2:
            continue
        page_strings.setdefault(text, set()).add(block.page_num)

    threshold = max(3, page_count * 0.4)
    repeated = {text for text, pages in page_strings.items() if len(pages) >= threshold}

    # Figure/chart fonts
    font_short_chars: Counter[str] = Counter()
    font_total_chars: Counter[str] = Counter()
    for block in blocks:
        block_text = block.text.strip()
        is_short = len(block_text) < 60 and len(block.lines) <= 3
        for line in block.lines:
            for span in line.spans:
                n = len(span.text)
                font_total_chars[span.font_name] += n
                if is_short:
                    font_short_chars[span.font_name] += n

    font_colors: dict[str, set[int]] = {}
    for block in blocks:
        for line in block.lines:
            for span in line.spans:
                font_colors.setdefault(span.font_name, set()).add(span.color)

    figure_fonts: set[str] = set()
    for font_name, total in font_total_chars.items():
        if font_name == body_font_name:
            continue
        if total < 50:
            continue
        short_ratio = font_short_chars.get(font_name, 0) / total
        if short_ratio < 0.95:
            continue
        colors = font_colors.get(font_name, set())
        if all(c == body_color or c == 0x000000 for c in colors):
            figure_fonts.add(font_name)

    return _DocStats(
        body_font_size=body_font_size,
        body_font_name=body_font_name,
        body_color=body_color,
        page_count=page_count,
        page_height=page_height,
        repeated_page_strings=repeated,
        figure_fonts=figure_fonts,
    )


# ── Heading scoring ─────────────────────────────────────────────────

HEADING_NUMBER_RE = re.compile(
    r'^(?:'
    r'(?:chapter|part|section|appendix)\s+\w+'
    r'|\d+(?:\.\d+)+\.?\s'
    r'|\d+\.?\s+[A-Z]'
    r'|[IVXLC]{2,}\.?\s'
    r')',
    re.IGNORECASE,
)

SECTION_KEYWORDS = frozenset({
    'abstract', 'introduction', 'background', 'related work', 'related works',
    'methodology', 'methods', 'method', 'approach', 'model', 'architecture',
    'experiments', 'experimental evaluation', 'experimental setup',
    'results', 'discussion', 'analysis', 'evaluation',
    'conclusion', 'conclusions', 'summary',
    'references', 'bibliography', 'acknowledgments', 'acknowledgements',
    'appendix', 'supplementary', 'notation', 'preliminaries', 'overview',
})


def _score_span_run(
    spans: list[_SpanInfo],
    text: str,
    stats: _DocStats,
) -> tuple[float, list[str]]:
    """Score a sequence of spans as a potential heading."""
    score = 0.0
    signals: list[str] = []

    if not text or len(text) > 200:
        return 0.0, []

    max_size = max(s.font_size for s in spans)
    size_diff = max_size - stats.body_font_size
    if size_diff > 1.0:
        size_score = 2.0 + size_diff * 0.3
        score += size_score
        signals.append(f"larger font ({max_size:.1f} vs body {stats.body_font_size:.1f}, +{size_score:.1f})")

    non_ws_spans = [s for s in spans if s.text.strip()]
    if non_ws_spans:
        heading_fonts = {s.font_name for s in non_ws_spans}
        if all(f != stats.body_font_name for f in heading_fonts):
            score += 1.5
            signals.append(f"non-body font ({', '.join(heading_fonts)} vs {stats.body_font_name})")

    all_bold = all(s.is_bold for s in non_ws_spans) if non_ws_spans else False
    if all_bold:
        score += 2.0
        signals.append("all bold")

    if non_ws_spans and stats.body_color is not None:
        heading_colors = {s.color for s in non_ws_spans}
        if all(c != stats.body_color for c in heading_colors):
            score += 2.0
            color_strs = [f"0x{c:06X}" for c in heading_colors]
            signals.append(f"non-body color ({', '.join(color_strs)} vs body 0x{stats.body_color:06X})")

    if HEADING_NUMBER_RE.match(text):
        score += 3.0
        signals.append("numbering pattern")

    stripped_lower = re.sub(r'^[\d.\s]+', '', text).strip().lower()
    if stripped_lower in SECTION_KEYWORDS:
        score += 2.0
        signals.append(f'section keyword: "{stripped_lower}"')

    if len(text) < 80:
        score += 0.5
        signals.append("short text")

    alpha_chars = [c for c in text if c.isalpha()]
    if len(alpha_chars) > 3 and all(c.isupper() for c in alpha_chars):
        score += 1.0
        signals.append("ALL CAPS")

    return score, signals


# ── Filtering helpers ───────────────────────────────────────────────


def _is_body_line(line: _LineInfo, stats: _DocStats) -> bool:
    """Check if a line is composed of body-font spans."""
    non_ws = [s for s in line.spans if s.text.strip()]
    if not non_ws:
        return False
    for s in non_ws:
        if s.font_name != stats.body_font_name:
            continue
        if s.is_bold:
            continue
        if abs(s.font_size - stats.body_font_size) > 1.5:
            continue
        if s.color != stats.body_color:
            continue
        return True
    return False


def _looks_like_figure_or_table_label(text: str) -> bool:
    """Reject text that looks like figure/table content rather than a heading."""
    t = text.strip()
    if re.match(r'^(Table|Figure|Fig\.)\s+\d', t, re.IGNORECASE):
        return True
    alpha = [c for c in t if c.isalpha()]
    if len(alpha) < 2:
        return True
    if re.match(r'^[\d.,+\-=k%\s]+$', t):
        return True
    if alpha:
        unique_alpha = set(c.lower() for c in alpha)
        if len(unique_alpha) <= 1 and len(t) < 30:
            return True
    if len(alpha) < 4 and len(t) < 10:
        return True
    return False


# ── Heading candidate detection strategies ──────────────────────────


def _try_contiguous_heading_lines(
    block: _BlockInfo,
    block_index: int,
    stats: _DocStats,
    candidates: list[_RawCandidate],
) -> None:
    """Find contiguous runs of non-body lines and score them as headings."""
    line_is_body = [_is_body_line(line, stats) for line in block.lines]

    runs: list[tuple[int, int]] = []
    run_start = None
    for idx, is_body in enumerate(line_is_body):
        if not is_body:
            if run_start is None:
                run_start = idx
        else:
            if run_start is not None:
                runs.append((run_start, idx))
                run_start = None
    if run_start is not None:
        runs.append((run_start, len(block.lines)))

    for start, end in runs:
        if end - start == len(block.lines):
            continue

        heading_lines = block.lines[start:end]
        heading_spans = [s for ln in heading_lines for s in ln.spans]
        heading_text = "\n".join(ln.text for ln in heading_lines).strip()

        if not heading_text or len(heading_text) > 200:
            continue
        if _looks_like_figure_or_table_label(heading_text):
            continue

        score, signals = _score_span_run(heading_spans, heading_text, stats)

        if start == 0:
            score += 1.0
            signals.append("followed by body text on next line")
        elif end == len(block.lines):
            score += 1.0
            signals.append("preceded by other text in same block")
        else:
            score += 0.5
            signals.append("embedded within block")

        if score >= 4.0:
            source = "leading-lines" if start == 0 else "trailing-lines"
            candidates.append(_RawCandidate(
                text=heading_text,
                page_num=block.page_num,
                block_index=block_index,
                font_name=heading_spans[0].font_name,
                font_size=max(s.font_size for s in heading_spans),
                signals=signals,
                score=score,
                source=source,
            ))


def _find_heading_candidates(
    blocks: list[_BlockInfo], stats: _DocStats,
) -> list[_RawCandidate]:
    """Detect heading candidates using three strategies."""
    candidates: list[_RawCandidate] = []

    for i, block in enumerate(blocks):
        block_text = block.text.strip()
        if not block_text:
            continue

        if block_text in stats.repeated_page_strings:
            continue
        if _looks_like_figure_or_table_label(block_text):
            continue

        all_spans = [s for line in block.lines for s in line.spans]
        non_ws_fonts = {s.font_name for s in all_spans if s.text.strip()}
        if non_ws_fonts and non_ws_fonts.issubset(stats.figure_fonts):
            continue

        # Strategy 1: Isolated heading block
        if len(block.lines) <= 3 and len(block_text) <= 200:
            score, signals = _score_span_run(all_spans, block_text, stats)
            if score >= 4.0:
                candidates.append(_RawCandidate(
                    text=block_text,
                    page_num=block.page_num,
                    block_index=i,
                    font_name=all_spans[0].font_name if all_spans else "",
                    font_size=max((s.font_size for s in all_spans), default=0),
                    signals=signals,
                    score=score,
                    source="block",
                ))
                continue

        # Strategy 2: Leading spans of first line differ from trailing
        first_line = block.lines[0]
        if len(first_line.spans) >= 2:
            leading_spans: list[_SpanInfo] = []
            for span in first_line.spans:
                if span.font_name == stats.body_font_name and not span.is_bold:
                    break
                if span.text.strip():
                    leading_spans.append(span)
                elif leading_spans:
                    leading_spans.append(span)

            if leading_spans:
                heading_text = "".join(s.text for s in leading_spans).strip()
                remaining_spans = first_line.spans[len(leading_spans):]
                remaining_text = "".join(s.text for s in remaining_spans).strip()

                if heading_text and len(heading_text) <= 200 and remaining_text:
                    if not _looks_like_figure_or_table_label(heading_text):
                        score, signals = _score_span_run(
                            leading_spans, heading_text, stats,
                        )
                        score += 1.0
                        signals.append("followed by body text in same line")

                        if score >= 4.0:
                            candidates.append(_RawCandidate(
                                text=heading_text,
                                page_num=block.page_num,
                                block_index=i,
                                font_name=leading_spans[0].font_name,
                                font_size=max(
                                    s.font_size for s in leading_spans
                                ),
                                signals=signals,
                                score=score,
                                source="leading-span",
                            ))
                            continue

        # Strategy 3: Contiguous non-body lines
        if len(block.lines) >= 2:
            _try_contiguous_heading_lines(block, i, stats, candidates)

    _apply_vertical_gap_signal(candidates, blocks, stats)
    candidates = _deduplicate_candidates(candidates)
    return candidates


# ── Post-processing ─────────────────────────────────────────────────


def _apply_vertical_gap_signal(
    candidates: list[_RawCandidate],
    blocks: list[_BlockInfo],
    stats: _DocStats,
) -> None:
    """Boost candidates that are followed by a large vertical gap."""
    gap_threshold = stats.page_height * 0.15

    for candidate in candidates:
        if candidate.source != "block":
            continue

        block = blocks[candidate.block_index]
        block_bottom = block.bbox[3]

        next_top = None
        for j in range(candidate.block_index + 1, len(blocks)):
            other = blocks[j]
            if other.page_num != block.page_num:
                break
            if other.text.strip():
                next_top = other.bbox[1]
                break

        if next_top is not None:
            gap = next_top - block_bottom
            if gap > gap_threshold:
                gap_pct = gap / stats.page_height * 100
                candidate.score += 2.0
                candidate.signals.append(
                    f"vertical gap ({gap:.0f}pt, {gap_pct:.0f}% of page)"
                )


_NUMBERING_PREFIX_RE = re.compile(
    r'^(\d+(?:\.\d+)*\.?\s*)'
    r'|^([IVXLC]{2,}\.?\s*)'
    r'|^((?:chapter|part|section|appendix)\s+\w+\s*)',
    re.IGNORECASE,
)

_TRAILING_PAGE_NUM_RE = re.compile(r'\s*\n?\d+\s*$')


def _normalize_heading(text: str) -> tuple[str | None, set[str]]:
    """Normalize a heading for deduplication."""
    t = text.strip()
    m = _NUMBERING_PREFIX_RE.match(t)
    prefix = m.group().strip() if m else None
    remainder = t[m.end():] if m else t
    remainder = _TRAILING_PAGE_NUM_RE.sub('', remainder)
    words = set(re.findall(r'[a-z]+', remainder.lower()))
    return prefix, words


def _deduplicate_candidates(
    candidates: list[_RawCandidate],
) -> list[_RawCandidate]:
    """Remove near-duplicate candidates, keeping the highest-scoring version."""
    sorted_cands = sorted(candidates, key=lambda c: c.score, reverse=True)
    kept: list[_RawCandidate] = []
    kept_normalized: list[tuple[str | None, set[str]]] = []

    for cand in sorted_cands:
        prefix, words = _normalize_heading(cand.text)

        is_dup = False
        for kept_prefix, kept_words in kept_normalized:
            if prefix and kept_prefix and prefix == kept_prefix:
                is_dup = True
                break
            if prefix and kept_prefix and prefix != kept_prefix:
                continue
            if words and kept_words:
                intersection = len(words & kept_words)
                union = len(words | kept_words)
                if union > 0 and intersection / union >= 0.7:
                    is_dup = True
                    break

        if not is_dup:
            kept.append(cand)
            kept_normalized.append((prefix, words))

    return kept


# ── Context extraction ──────────────────────────────────────────────


def _get_context(
    candidate: _RawCandidate,
    blocks: list[_BlockInfo],
    max_chars: int = 120,
) -> tuple[str, str]:
    """Get text before and after a candidate's block for LLM context."""
    idx = candidate.block_index

    before = ""
    for j in range(idx - 1, max(idx - 4, -1), -1):
        text = blocks[j].text.strip()
        if text and blocks[j].page_num == candidate.page_num:
            before = text[:max_chars]
            break

    after = ""
    for j in range(idx + 1, min(idx + 4, len(blocks))):
        text = blocks[j].text.strip()
        if text:
            after = text[:max_chars]
            break

    return before, after


# ── Public extractor class ──────────────────────────────────────────


class PdfExtractor:
    """Extract text and heading candidates from a PDF document.

    Implements the ``DocumentExtractor`` protocol.
    """

    def extract(self, source: bytes) -> ExtractionResult:
        doc = fitz.open(stream=source, filetype="pdf")
        try:
            return self._extract_from_doc(doc)
        finally:
            doc.close()

    def _extract_from_doc(self, doc: fitz.Document) -> ExtractionResult:
        blocks = _extract_blocks(doc)
        stats = _compute_doc_stats(doc, blocks)
        raw_candidates = _find_heading_candidates(blocks, stats)

        # Build full plain text and track block -> char offset mapping
        block_char_offset: dict[int, int] = {}
        parts: list[str] = []
        offset = 0
        for i, block in enumerate(blocks):
            if not block.text.strip():
                continue
            if parts:
                offset += 2  # "\n\n" separator
            block_char_offset[i] = offset
            parts.append(block.text)
            offset += len(block.text)
        raw_text = "\n\n".join(parts)

        # Convert internal candidates to protocol HeadingCandidates
        candidates: list[HeadingCandidate] = []
        for rc in raw_candidates:
            context_before, context_after = _get_context(rc, blocks)
            block = blocks[rc.block_index]
            block_offset = block_char_offset.get(rc.block_index, 0)
            delta = max(block.text.find(rc.text), 0)
            candidates.append(HeadingCandidate(
                text=rc.text,
                page=rc.page_num,
                position_index=rc.block_index,
                score=rc.score,
                signals=rc.signals,
                source=rc.source,
                context_before=context_before,
                context_after=context_after,
                text_offset=block_offset + delta,
            ))

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)

        # Document title from metadata
        meta = doc.metadata or {}
        doc_title = meta.get("title") or None

        # Metadata for persistence
        metadata = {
            "body_font_name": stats.body_font_name,
            "body_font_size": stats.body_font_size,
            "body_color": f"0x{stats.body_color:06X}",
            "page_height": stats.page_height,
            "repeated_page_strings": sorted(stats.repeated_page_strings),
            "figure_fonts": sorted(stats.figure_fonts),
        }

        return ExtractionResult(
            raw_text=raw_text,
            candidates=candidates,
            doc_title=doc_title,
            page_count=len(doc),
            metadata=metadata,
        )
