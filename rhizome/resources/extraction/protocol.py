"""Protocol and shared data types for document extraction.

Each document format (PDF, EPUB, HTML, etc.) implements the
``DocumentExtractor`` protocol.  The format-agnostic LLM pipeline in
``pipeline.py`` consumes the ``ExtractionResult`` they produce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class HeadingCandidate:
    """A heading candidate produced by a format-specific extractor.

    Attributes:
        text: The raw heading text as extracted.
        page: 0-indexed page number, or ``None`` for non-paginated formats.
        position_index: Extractor-defined ordering index (e.g. block index
            for PDFs).  Used to establish document order across candidates.
        score: Weighted heuristic confidence score.
        signals: Human-readable reasons this was flagged as a candidate.
        source: Name of the detection strategy that produced this candidate
            (e.g. "block", "leading-span", "html-tag").
        context_before: Short excerpt of preceding text, for LLM context.
        context_after: Short excerpt of following text, for LLM context.
        text_offset: Character offset where this candidate's text begins
            in ``ExtractionResult.raw_text``, or ``None`` if not computed.
    """

    text: str
    page: int | None
    position_index: int
    score: float
    signals: list[str]
    source: str
    context_before: str = ""
    context_after: str = ""
    text_offset: int | None = None


@dataclass
class ExtractionResult:
    """Output of a ``DocumentExtractor``.

    Attributes:
        raw_text: Full plain-text content of the document.
        candidates: Heading candidates sorted by score descending.
        doc_title: Document title from metadata, if available.
        page_count: Total pages, or ``None`` for non-paginated formats.
        metadata: Format-specific statistics to be persisted as
            ``Resource.source_metadata`` (e.g. body font info for PDFs).
    """

    raw_text: str
    candidates: list[HeadingCandidate]
    doc_title: str | None = None
    page_count: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Section:
    """A confirmed section in the document, produced by the LLM pipeline.

    Attributes:
        title: Cleaned section title (numbering preserved when present).
        depth: 1-based nesting depth (1 = top-level chapter/part).
        page: 0-indexed page of the heading, or ``None``.
        position_index: Matches the originating candidate's position_index.
        start_offset: Character offset in ``raw_text`` where this section
            begins, or ``None`` if not yet computed.
        children: Nested child sections.
    """

    title: str
    depth: int
    page: int | None
    position_index: int
    start_offset: int | None = None
    children: list[Section] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {
            "title": self.title,
            "depth": self.depth,
            "page": self.page,
            "position_index": self.position_index,
        }
        if self.start_offset is not None:
            d["start_offset"] = self.start_offset
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d

    def tree_str(self, indent: int = 0) -> str:
        prefix = "  " * indent
        page_str = f" (p.{self.page})" if self.page is not None else ""
        lines = [f"{prefix}{self.title}{page_str}"]
        for child in self.children:
            lines.append(child.tree_str(indent + 1))
        return "\n".join(lines)


@runtime_checkable
class DocumentExtractor(Protocol):
    """Protocol for format-specific document extractors.

    Each implementation handles a single document format (PDF, EPUB, etc.)
    and produces a format-agnostic ``ExtractionResult`` containing the
    document's full text and heading candidates with heuristic scores.

    The extractor is responsible for:
    - Extracting plain text from the source
    - Detecting heading candidates using format-specific heuristics
    - Providing surrounding context for each candidate
    - Computing format-specific metadata for persistence

    The extractor is NOT responsible for:
    - LLM-based refinement (handled by ``pipeline.detect_sections``)
    - Persisting results to the database
    - Chunking or embedding
    """

    def extract(self, source: bytes) -> ExtractionResult:
        """Extract text and heading candidates from a document.

        Args:
            source: Raw bytes of the document (e.g. PDF file contents).

        Returns:
            ExtractionResult with full text, candidates, and metadata.
        """
        ...
