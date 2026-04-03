# rhizome/resources/extraction/

Automatic section detection pipeline for document resources.

## Architecture

The pipeline has two stages:

1. **Heuristic extraction** (format-specific) — A `DocumentExtractor` implementation analyzes a document and produces `HeadingCandidate` objects with confidence scores. Each format (PDF, EPUB, HTML) has its own extractor using format-appropriate signals (font size, HTML tags, etc.).

2. **LLM refinement** (format-agnostic) — The `detect_sections()` function in `pipeline.py` processes candidates in score-descending batches through an LLM to accept/reject, assign depth, and clean titles. It exits early when consecutive batches yield no new sections.

## Modules

- **`protocol.py`** — `DocumentExtractor` protocol, shared dataclasses (`HeadingCandidate`, `ExtractionResult`, `Section`). All extractors produce these types; the pipeline consumes them.
- **`pdf.py`** — `PdfExtractor` implementing `DocumentExtractor` for PDF files. Uses pymupdf (fitz) for text extraction and three heuristic heading-detection strategies: isolated block, leading-span, and contiguous non-body lines. Scoring is based on font size/weight/color, numbering patterns, section keywords, and vertical layout.
- **`pipeline.py`** — Format-agnostic async LLM pipeline: batching, early exit, tree building, cleanup pass. No knowledge of any specific document format. Accepts any langchain `BaseChatModel`, uses `.with_structured_output()` with pydantic response schemas.

## Adding a New Format

1. Create a new module (e.g. `epub.py`) with a class implementing `DocumentExtractor`
2. The `extract(source: bytes)` method receives raw file bytes and returns an `ExtractionResult`
3. Register it in `__init__.py`

## Data Flow

```
source bytes
    │
    ▼
DocumentExtractor.extract()     ← format-specific heuristics
    │
    ▼
ExtractionResult
  ├── raw_text                  ← full plain text
  ├── candidates[]              ← HeadingCandidate with scores
  └── metadata                  ← format-specific stats (persisted)
    │
    ▼
detect_sections(result, llm)    ← format-agnostic LLM pipeline
    │
    ▼
list[Section]                   ← confirmed section tree
```
