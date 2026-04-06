"""Embedding helpers — chunking, embedding, and storage for resource documents."""

from __future__ import annotations

import os
import struct
import time

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rhizome.db.operations import add_chunks, get_resource
from rhizome.logs import get_logger

_log = get_logger("resources.embeddings")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=100,
    add_start_index=True,
)


def chunk_text(text: str) -> list[dict]:
    """Split text into chunks with positional metadata.

    Returns list of dicts with chunk_index, start_offset, end_offset.
    """
    docs = _splitter.create_documents([text])
    return [
        {
            "chunk_index": idx,
            "start_offset": doc.metadata["start_index"],
            "end_offset": doc.metadata["start_index"] + len(doc.page_content),
        }
        for idx, doc in enumerate(docs)
    ]


# ---------------------------------------------------------------------------
# Embeddings (VoyageAI via REST)
#
# We call the Voyage API directly instead of using the `voyageai` Python SDK
# because the SDK (v0.3.7) crashes on import with our Pydantic 2.x setup.
# The issue is in voyageai/object/multimodal_embeddings.py: a Pydantic v1
# compat-layer model uses Field(..., min_items=1), which raises ValueError
# in the v1 shim. The langchain-voyageai wrapper depends on this SDK so it's
# also unusable. Replace with the SDK once upstream ships a fix.
# (Encountered 2026-03-27)
# ---------------------------------------------------------------------------

def get_voyage_api_key() -> str:
    """Return the Voyage API key from the environment, or raise RuntimeError."""
    key = os.environ.get("VOYAGE_API_KEY", "")
    if not key:
        raise RuntimeError(
            "VOYAGE_API_KEY environment variable is required for embeddings. "
            "Set it and try again."
        )
    return key


def embed_batch(texts: list[str], api_key: str, model: str = "voyage-3.5") -> list[list[float]]:
    """Embed a batch of texts via Voyage REST API with retry."""
    for attempt in range(5):
        resp = httpx.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"input": texts, "model": model},
            timeout=60,
        )
        if resp.status_code == 429:
            wait = min(2 ** attempt, 16)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()["data"]
        data.sort(key=lambda x: x["index"])
        return [d["embedding"] for d in data]
    resp.raise_for_status()
    return []  # unreachable, but satisfies type checker


def floats_to_bytes(floats: list[float]) -> bytes:
    """Pack a list of floats into raw bytes (float32)."""
    return struct.pack(f"{len(floats)}f", *floats)


def embed_chunks(raw_text: str, chunks: list[dict], api_key: str) -> list[dict]:
    """Add embedding bytes to each chunk dict. Batches in groups of 128."""
    texts = [raw_text[c["start_offset"]:c["end_offset"]] for c in chunks]
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), 128):
        batch = texts[i:i + 128]
        all_embeddings.extend(embed_batch(batch, api_key))
    for chunk, emb in zip(chunks, all_embeddings):
        chunk["embedding"] = floats_to_bytes(emb)
    return chunks


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

async def has_embeddings(session_factory, resource_id: int) -> bool:
    """Check if a resource has any chunks with embeddings."""
    async with session_factory() as session:
        resource = await get_resource(session, resource_id)
        if resource is None or not resource.chunks:
            return False
        return any(c.embedding is not None for c in resource.chunks)


async def compute_embeddings(session_factory, resource_id: int) -> None:
    """Chunk and embed a resource, storing results in the DB.

    Handles two cases:
        - No chunks exist yet: creates chunks from raw_text and embeds them.
        - Chunks exist but lack embeddings: computes and attaches embeddings.

    Raises on failure (missing API key, API errors, missing raw_text, etc.).
    """
    api_key = get_voyage_api_key()

    async with session_factory() as session:
        resource = await get_resource(session, resource_id)
        if resource is None:
            raise ValueError(f"Resource {resource_id} not found.")
        if not resource.raw_text:
            raise ValueError(f"Resource {resource_id} has no raw_text to embed.")

        raw_text = resource.raw_text
        existing_chunks = resource.chunks

    if existing_chunks and all(c.embedding is None for c in existing_chunks):
        # Chunks exist but need embeddings — rebuild chunk dicts from DB rows
        # and compute embeddings for them.
        chunk_dicts = [
            {
                "chunk_index": c.chunk_index,
                "start_offset": c.start_offset,
                "end_offset": c.end_offset,
            }
            for c in existing_chunks
        ]
        chunk_dicts = embed_chunks(raw_text, chunk_dicts, api_key)

        # Update existing chunk rows with embeddings.
        async with session_factory() as session:
            resource = await get_resource(session, resource_id)
            for chunk_obj, chunk_dict in zip(resource.chunks, chunk_dicts):
                chunk_obj.embedding = chunk_dict["embedding"]
            await session.commit()

        _log.info("Embedded %d existing chunks for resource %d", len(chunk_dicts), resource_id)
    else:
        # No chunks at all — create from scratch.
        chunk_dicts = chunk_text(raw_text)
        chunk_dicts = embed_chunks(raw_text, chunk_dicts, api_key)

        async with session_factory() as session:
            await add_chunks(session, resource_id, chunk_dicts)
            await session.commit()

        _log.info("Created and embedded %d chunks for resource %d", len(chunk_dicts), resource_id)
