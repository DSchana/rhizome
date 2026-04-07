"""Resource extraction pipeline — automatic section discovery for documents."""

from rhizome.resources.extraction.protocol import (
    DocumentExtractor,
    ExtractionResult,
    HeadingCandidate,
    Section,
)
from rhizome.resources.extraction.pipeline import (
    PipelineStats,
    detect_sections,
    estimate_extraction_tokens,
    get_extractor,
    extract_document_subsections,
    register_extractor,
)
from rhizome.resources.extraction.pdf import PdfExtractor

__all__ = [
    "DocumentExtractor",
    "ExtractionResult",
    "HeadingCandidate",
    "PdfExtractor",
    "PipelineStats",
    "Section",
    "detect_sections",
    "estimate_extraction_tokens",
    "get_extractor",
    "extract_document_subsections",
    "register_extractor",
]
