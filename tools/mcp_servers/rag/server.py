"""RAG MCP Server — check/write cache and search the shared Vertex AI RAG corpus."""
from __future__ import annotations

import json
import logging
import os
_PORT = int(os.environ.get("PORT", 8080))
import time
from datetime import datetime, timezone

import vertexai
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("stratova-rag", host="0.0.0.0", port=_PORT)

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
# RAG corpus is in us-west1 — RAG_LOCATION must match the corpus location,
# NOT the general GOOGLE_CLOUD_LOCATION (which is us-central1 for Agent Engine).
LOCATION = os.environ.get("RAG_LOCATION", os.environ.get("GOOGLE_CLOUD_LOCATION", "us-west1"))
CORPUS   = os.environ.get("KNOWLEDGE_IQ_RAG_CORPUS", "")

CACHE_TTL: dict[str, float] = {
    "enrichment": 7 * 24 * 3600,
    "crm_read": 3600,
    "website": 86400,
    "package": 86400,
}
MIN_SCORE: dict[str, float] = {
    "enrichment": 0.85,
    "crm_read": 0.90,
    "website": 0.80,
    "package": 0.80,
}


def _init_vertexai() -> None:
    if PROJECT:
        vertexai.init(project=PROJECT, location=LOCATION)


@mcp.tool()
def check_rag_cache(query: str, cache_type: str) -> dict:
    """Search RAG corpus for cached data matching the query.

    Returns {"hit": True, "data": {...}, "age_seconds": N} if found and fresh,
    or {"hit": False} if not found or stale.

    Args:
        query: Semantic search query e.g. "company enrichment vantageclinical.com"
        cache_type: One of: enrichment, crm_read, website, package
    """
    _init_vertexai()
    try:
        from vertexai.preview import rag

        results = rag.retrieval_query(
            rag_resources=[rag.RagResource(rag_corpus=CORPUS)],
            text=query,
            similarity_top_k=3,
        )
        min_score = MIN_SCORE.get(cache_type, 0.80)
        ttl = CACHE_TTL.get(cache_type, 3600)
        now = datetime.now(timezone.utc).timestamp()

        for chunk in results.contexts.contexts:
            if chunk.score >= min_score:
                try:
                    data = json.loads(chunk.text)
                    cached_at = data.get("_cached_at", 0)
                    age = now - cached_at
                    if age <= ttl:
                        return {"hit": True, "data": data, "age_seconds": int(age)}
                except (json.JSONDecodeError, KeyError):
                    continue
        return {"hit": False}
    except Exception as exc:
        logger.error("check_rag_cache error: %s", exc)
        return {"hit": False, "error": str(exc)}


@mcp.tool()
def write_rag_cache(cache_key: str, data: dict, cache_type: str) -> dict:
    """Write structured data to the RAG corpus with TTL metadata.

    Tags the document with _cache_key, _cache_type, _cached_at so
    check_rag_cache() can validate freshness on the next lookup.

    Args:
        cache_key: Unique identifier e.g. "company_enrichment_vantageclinical.com"
        data: Dict to store. Will be JSON-serialised and ingested into RAG.
        cache_type: One of: enrichment, crm_read, website, package
    """
    _init_vertexai()
    try:
        from vertexai.preview import rag
        import tempfile, pathlib

        data["_cache_key"] = cache_key
        data["_cache_type"] = cache_type
        data["_cached_at"] = datetime.now(timezone.utc).timestamp()
        doc_text = json.dumps(data, ensure_ascii=False)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(doc_text)
            tmp_path = f.name

        rag.upload_file(
            corpus_name=CORPUS,
            path=tmp_path,
            display_name=f"cache_{cache_key[:80]}",
            description=f"cache_type={cache_type}",
        )
        pathlib.Path(tmp_path).unlink(missing_ok=True)
        return {"status": "written", "cache_key": cache_key, "cache_type": cache_type}
    except Exception as exc:
        logger.error("write_rag_cache error: %s", exc)
        return {"status": "error", "error": str(exc)}


@mcp.tool()
def search_rag(query: str, top_k: int = 5) -> dict:
    """Semantic search over the shared RAG corpus.

    Args:
        query: Natural language or keyword search query.
        top_k: Maximum number of chunks to return (default 5, max 20).
    """
    _init_vertexai()
    try:
        from vertexai.preview import rag

        top_k = min(top_k, 20)
        results = rag.retrieval_query(
            rag_resources=[rag.RagResource(rag_corpus=CORPUS)],
            text=query,
            similarity_top_k=top_k,
        )
        chunks = [
            {"text": c.text, "score": c.score, "source": c.source_uri}
            for c in results.contexts.contexts
        ]
        return {"chunks": chunks, "count": len(chunks), "query": query}
    except Exception as exc:
        logger.error("search_rag error: %s", exc)
        return {"chunks": [], "count": 0, "error": str(exc)}


@mcp.tool()
def ingest_document(title: str, content: str, source_url: str = "") -> dict:
    """Ingest a text document into the shared RAG corpus.

    Args:
        title: Document title shown in search results.
        content: Plain text content to index (max 100k chars).
        source_url: Optional URL the content was fetched from.
    """
    _init_vertexai()
    try:
        from vertexai.preview import rag
        import tempfile, pathlib

        header = f"Title: {title}\nSource: {source_url}\n\n" if source_url else f"Title: {title}\n\n"
        full_text = header + content[:100_000]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(full_text)
            tmp_path = f.name

        rag.upload_file(
            corpus_name=CORPUS,
            path=tmp_path,
            display_name=title[:80],
            description=source_url or "ingested document",
        )
        pathlib.Path(tmp_path).unlink(missing_ok=True)
        return {"status": "ingested", "title": title, "chars": len(full_text)}
    except Exception as exc:
        logger.error("ingest_document error: %s", exc)
        return {"status": "error", "error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
