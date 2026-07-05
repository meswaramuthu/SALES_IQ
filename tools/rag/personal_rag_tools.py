"""Personal-scope RAG tools for the personal assistant agent.

Tools exposed:
  search_personal_knowledge  — RAG retrieval filtered to the user's own uploaded files
  list_my_documents          — List all files the user has uploaded personally
  upload_to_personal_knowledge — Route an upload through document_mining with personal scope

Usage:
    from tools.rag.personal_rag_tools import build_personal_rag_tools
    tools = build_personal_rag_tools(config_getter=get_config)
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Callable

from tools.rag.rag_ingest_utils import (
    get_personal_file_names,
    list_personal_files,
)

logger = logging.getLogger(__name__)

_DEFAULT_PERSONAL_REGISTRY_URI = (
    "gs://stratova-platform/knowledge-iq/personal_file_registry.json"
)
_DEFAULT_SCOPE_REGISTRY_URI = (
    "gs://stratova-platform/knowledge-iq/scope_file_registry.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_id(tool_context) -> str:
    """Extract a stable user identifier from the ADK tool context."""
    if tool_context is None:
        return "anonymous"
    uid = getattr(tool_context, "user_id", None) or ""
    if uid.strip():
        return uid.strip()
    try:
        uid = tool_context._invocation_context.session.user_id or ""
        if uid.strip():
            return uid.strip()
    except Exception:
        pass
    return "anonymous"


def _get_session_id(tool_context) -> str:
    if tool_context is None:
        return "default"
    try:
        return tool_context._invocation_context.session.id or "default"
    except Exception:
        pass
    return "default"


def _init_vertexai(resource_name: str) -> None:
    import vertexai
    from google.cloud.aiplatform import initializer

    m = re.search(r"projects/([^/]+)/locations/([^/]+)/", resource_name)
    if not m:
        return
    project, location = m.group(1), m.group(2)
    if getattr(initializer.global_config, "location", None) != location:
        vertexai.init(project=project, location=location)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_personal_rag_tools(config_getter: Callable) -> list[Callable]:
    """Return tool functions for the personal assistant, wired to config_getter."""

    # ------------------------------------------------------------------ #
    # TOOL 1: search personal knowledge                                    #
    # ------------------------------------------------------------------ #

    def search_personal_knowledge(
        query: str,
        max_results: int = 5,
        tool_context=None,
    ) -> dict:
        """Search documents you have personally uploaded to your knowledge base.

        Only returns results from YOUR files — other users' documents are not visible.

        Args:
            query: The question or topic to search for.
            max_results: Number of results to return (default 5, max 10).

        Returns:
            dict with: results (list of {text, score, source_file}), count, query.
        """
        cfg = config_getter().tools.get("rag")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "RAG is not configured."}

        corpus = cfg.config.get("corpus", "")
        registry_uri = cfg.config.get(
            "personal_registry_uri",
            _DEFAULT_PERSONAL_REGISTRY_URI,
        )

        if not corpus:
            return {"status": "error", "message": "RAG corpus is not configured."}

        user_id = _get_user_id(tool_context)
        personal_file_names = get_personal_file_names(user_id, registry_uri)

        if not personal_file_names:
            return {
                "status": "no_documents",
                "message": (
                    "You have no personal documents in your knowledge base yet. "
                    "Upload a document first using the upload tool."
                ),
                "results": [],
                "count": 0,
            }

        # Extract just the RAG file IDs (last segment of resource name)
        file_ids = [n.rsplit("/", 1)[-1] for n in personal_file_names]
        k = max(1, min(int(max_results), 10))

        try:
            from vertexai.preview import rag

            _init_vertexai(corpus)
            response = rag.retrieval_query(
                rag_resources=[
                    rag.RagResource(
                        rag_corpus=corpus,
                        rag_file_ids=file_ids,
                    )
                ],
                text=query,
                similarity_top_k=k,
                vector_distance_threshold=0.6,
            )

            results = []
            for ctx in response.contexts.contexts:
                results.append({
                    "text": ctx.text,
                    "score": round(1.0 - float(ctx.distance), 4),
                    "source_file": ctx.source_uri or ctx.source_display_name or "",
                })

            if not results:
                return {
                    "status": "no_results",
                    "message": (
                        f"No relevant content found in your documents for: '{query}'. "
                        "Try rephrasing or upload more documents."
                    ),
                    "results": [],
                    "count": 0,
                    "query": query,
                }

            return {
                "status": "success",
                "results": results,
                "count": len(results),
                "query": query,
                "searched_files": len(file_ids),
            }

        except Exception as exc:
            logger.error("search_personal_knowledge error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------ #
    # TOOL 2: list my documents                                            #
    # ------------------------------------------------------------------ #

    def list_my_documents(tool_context=None) -> dict:
        """List all documents you have personally uploaded to your knowledge base.

        Returns:
            dict with: documents (list of {display_name, rag_file_name}), count.
        """
        cfg = config_getter().tools.get("rag")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "RAG is not configured."}

        registry_uri = cfg.config.get(
            "personal_registry_uri",
            _DEFAULT_PERSONAL_REGISTRY_URI,
        )

        user_id = _get_user_id(tool_context)
        files = list_personal_files(user_id, registry_uri)

        if not files:
            return {
                "status": "no_documents",
                "message": "You have no personal documents uploaded yet.",
                "documents": [],
                "count": 0,
            }

        return {
            "status": "success",
            "documents": files,
            "count": len(files),
            "user_id": user_id,
        }

    # ------------------------------------------------------------------ #
    # TOOL 3: upload to personal knowledge (routes to document_mining)     #
    # ------------------------------------------------------------------ #

    def upload_to_personal_knowledge(
        document_text: str,
        display_name: str,
        tool_context=None,
    ) -> dict:
        """Upload a document to your personal knowledge base.

        The document is processed by the document-mining agent and stored
        so that only YOU can retrieve it via search_personal_knowledge.

        Args:
            document_text: The full text content of the document to upload.
            display_name: A friendly name for the document (e.g. "Q4 notes.txt").

        Returns:
            dict with: status, message, rag_file_name (on success).
        """
        if not document_text or not document_text.strip():
            return {"status": "error", "message": "document_text is required."}
        if not display_name or not display_name.strip():
            return {"status": "error", "message": "display_name is required."}

        user_id = _get_user_id(tool_context)
        session_id = _get_session_id(tool_context)

        cfg = config_getter()
        dm_resource = ""
        sub_agents = cfg.sub_agents if hasattr(cfg, "sub_agents") else {}
        dm_cfg = sub_agents.get("document_mining_agent") if sub_agents else None
        if dm_cfg and getattr(dm_cfg, "enabled", False):
            dm_resource = getattr(dm_cfg, "resource_name", "") or ""

        if not dm_resource:
            return {
                "status": "error",
                "message": "document_mining_agent is not configured.",
            }

        # Construct a structured upload request that tells document_mining
        # to use personal scope and register the file under this user's ID.
        upload_request = (
            f"Upload the following document to the knowledge base.\n"
            f"accessibility_scope: personal\n"
            f"owner_user_id: {user_id}\n"
            f"display_name: {display_name}\n\n"
            f"Document content:\n{document_text[:15000]}"
        )

        try:
            # Route via local ADK or Agent Engine depending on resource prefix
            if dm_resource.startswith("local://"):
                result_text = _call_local_adk(dm_resource, upload_request, session_id)
            else:
                result_text = _call_agent_engine(dm_resource, upload_request, session_id)

            return {
                "status": "success",
                "message": (
                    f"Document '{display_name}' has been submitted to the knowledge base "
                    f"as a personal file.\n\n{result_text}"
                ),
            }

        except Exception as exc:
            logger.error("upload_to_personal_knowledge error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        search_personal_knowledge,
        list_my_documents,
        upload_to_personal_knowledge,
    ]


# ---------------------------------------------------------------------------
# A2A helpers (local ADK web server or Agent Engine)
# ---------------------------------------------------------------------------

def _call_local_adk(resource_name: str, message: str, session_id: str) -> str:
    """Call a local ADK agent running under `adk web`."""
    import os

    agent_name = resource_name.removeprefix("local://")
    base_url = os.getenv("ADK_LOCAL_BASE_URL", "http://localhost:8000").rstrip("/")

    # Create session
    sess_url = f"{base_url}/apps/{agent_name}/users/user/sessions"
    sess_req = urllib.request.Request(
        sess_url,
        data=json.dumps({"state": {}}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(sess_req, timeout=60) as resp:
        session = json.loads(resp.read())
    adk_session_id = session.get("id", session_id)

    # Send message
    run_url = f"{base_url}/apps/{agent_name}/users/user/sessions/{adk_session_id}/run"
    run_req = urllib.request.Request(
        run_url,
        data=json.dumps({"message": {"role": "user", "parts": [{"text": message}]}}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(run_req, timeout=120) as resp:
        events = json.loads(resp.read())

    # Extract last agent text
    for event in reversed(events if isinstance(events, list) else []):
        if event.get("author") != "user":
            for part in event.get("content", {}).get("parts", []):
                if part.get("text"):
                    return part["text"]
    return "Upload submitted."


def _call_agent_engine(resource_name: str, message: str, session_id: str) -> str:
    """Call a deployed Vertex AI Agent Engine agent."""
    import vertexai
    from vertexai import agent_engines

    _init_vertexai(resource_name)
    agent = agent_engines.get(resource_name)
    adk_session = agent.create_session(user_id=f"pa-{session_id}")
    text_parts = []
    for event in agent.stream_query(
        session_id=adk_session["id"],
        message=message,
        user_id=f"pa-{session_id}",
    ):
        content = event.get("content") or {}
        for part in content.get("parts", []):
            if part.get("text"):
                text_parts.append(part["text"])
    return " ".join(text_parts) if text_parts else "Upload submitted."
