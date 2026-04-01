"""Resource tools — loading and managing document resources for RAG."""

from __future__ import annotations

import hashlib
import os
import struct
import time
from typing import Literal

import httpx
from langchain.tools import tool
import pymupdf
from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rhizome.agent.tools.visibility import ToolVisibility, tool_visibility
from rhizome.db.models import LoadingPreference
from rhizome.db.operations import (
    add_chunks,
    create_resource,
    get_resource,
    list_resources,
)


# ---------------------------------------------------------------------------
# Text extraction (via LangChain document loaders)
# ---------------------------------------------------------------------------

def _extract_text(source: str, source_type: str) -> str:
    """Extract raw text from a source path or string."""
    if source_type == "text":
        return source

    if source_type == "pdf":
        doc = pymupdf.open(source)
        return "\n\n".join(page.get_text() for page in doc)

    raise ValueError(f"Unsupported source type: {source_type}")


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Approximate token count using langchain's estimator."""
    return count_tokens_approximately([HumanMessage(content=text)])


# ---------------------------------------------------------------------------
# Chunking (via LangChain text splitters)
# ---------------------------------------------------------------------------

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=100,
    add_start_index=True,
)


def _chunk_text(text: str) -> list[dict]:
    """Split text using RecursiveCharacterTextSplitter with start_index metadata.

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

def _get_voyage_api_key() -> str:
    key = os.environ.get("VOYAGE_API_KEY", "")
    if not key:
        raise RuntimeError(
            "VOYAGE_API_KEY environment variable is required for embeddings. "
            "Set it and try again."
        )
    return key


def _embed_batch(texts: list[str], api_key: str, model: str = "voyage-3.5") -> list[list[float]]:
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


def _floats_to_bytes(floats: list[float]) -> bytes:
    """Pack a list of floats into raw bytes (float32)."""
    return struct.pack(f"{len(floats)}f", *floats)


def _embed_chunks(raw_text: str, chunks: list[dict], api_key: str) -> list[dict]:
    """Add embedding bytes to each chunk dict. Batches in groups of 128."""
    texts = [raw_text[c["start_offset"]:c["end_offset"]] for c in chunks]
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), 128):
        batch = texts[i:i + 128]
        all_embeddings.extend(_embed_batch(batch, api_key))
    for chunk, emb in zip(chunks, all_embeddings):
        chunk["embedding"] = _floats_to_bytes(emb)
    return chunks


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

def build_resource_tools(session_factory) -> dict:
    """Build resource management tools with session_factory closed over."""

    @tool_visibility(ToolVisibility.DEFAULT)
    @tool("add_resource", description=(
        "Load a document as a resource for RAG. Extracts text, stores it in "
        "the database, and optionally creates vector embeddings for retrieval. "
        "Returns a resource manifest with ID, name, token estimate, and chunk count."
    ))
    async def add_resource_tool(
        name: str,
        source: str,
        source_type: Literal["text", "pdf"] = "text",
        loading_preference: Literal["auto", "context_stuff", "vector_store"] = "auto",
        blocking: bool = True,
    ) -> str:
        # 1. Extract text
        try:
            raw_text = _extract_text(source, source_type)
        except Exception as e:
            return f"Error extracting text: {e}"

        if not raw_text.strip():
            return "Error: no text content extracted from source."

        # 2. Compute metadata
        content_hash = hashlib.sha256(raw_text.encode()).hexdigest()
        estimated_tokens = _estimate_tokens(raw_text)
        pref = LoadingPreference(loading_preference)

        # 3. Create resource row
        async with session_factory() as session:
            resource = await create_resource(
                session,
                name=name,
                raw_text=raw_text,
                content_hash=content_hash,
                estimated_tokens=estimated_tokens,
                loading_preference=pref,
            )
            await session.commit()
            resource_id = resource.id

        # 4. Chunk and embed
        chunks = _chunk_text(raw_text)
        chunk_count = len(chunks)

        should_embed = pref in (LoadingPreference.auto, LoadingPreference.vector_store)

        if should_embed and blocking:
            try:
                api_key = _get_voyage_api_key()
                chunks = _embed_chunks(raw_text, chunks, api_key)
            except Exception as e:
                # Store chunks without embeddings, report the error
                async with session_factory() as session:
                    await add_chunks(session, resource_id, chunks)
                    await session.commit()
                return (
                    f"Resource [{resource_id}] '{name}' created "
                    f"({estimated_tokens} tokens, {chunk_count} chunks). "
                    f"Embedding failed: {e}"
                )

        # Store chunks (with or without embeddings)
        async with session_factory() as session:
            await add_chunks(session, resource_id, chunks)
            await session.commit()

        # 5. Build manifest
        status = "indexed" if should_embed and blocking else "stored (no embeddings)"
        return (
            f"Resource [{resource_id}] '{name}' created.\n"
            f"  Tokens: ~{estimated_tokens}\n"
            f"  Chunks: {chunk_count}\n"
            f"  Loading preference: {loading_preference}\n"
            f"  Status: {status}"
        )

    @tool_visibility(ToolVisibility.DEFAULT)
    @tool("list_resources", description=(
        "List all loaded resources with their IDs, names, token estimates, "
        "loading preferences, and whether they have embeddings."
    ))
    async def list_resources_tool() -> str:
        async with session_factory() as session:
            resources = await list_resources(session)

        if not resources:
            return "No resources loaded."

        lines = []
        for r in resources:
            lines.append(
                f"- [{r.id}] {r.name} "
                f"(~{r.estimated_tokens or '?'} tokens, "
                f"pref={r.loading_preference.value})"
            )
        return f"{len(resources)} resource(s):\n" + "\n".join(lines)

    @tool_visibility(ToolVisibility.DEFAULT)
    @tool("get_resource_info", description=(
        "Get detailed info about a resource by ID: name, summary, token count, "
        "chunk count, and loading preference."
    ))
    async def get_resource_info_tool(resource_id: int) -> str:
        async with session_factory() as session:
            resource = await get_resource(session, resource_id)

        if resource is None:
            return f"Resource {resource_id} not found."

        has_embeddings = any(c.embedding is not None for c in resource.chunks)
        lines = [
            f"Resource [{resource.id}]: {resource.name}",
            f"  Tokens: ~{resource.estimated_tokens or '?'}",
            f"  Chunks: {len(resource.chunks)}",
            f"  Has embeddings: {has_embeddings}",
            f"  Loading preference: {resource.loading_preference.value}",
        ]
        if resource.summary:
            lines.append(f"  Summary: {resource.summary}")
        return "\n".join(lines)

    return {
        "add_resource": add_resource_tool,
        "list_resources": list_resources_tool,
        "get_resource_info": get_resource_info_tool,
    }
