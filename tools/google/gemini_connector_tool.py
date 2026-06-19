"""Gemini Enterprise connector search tool.

Searches ALL data-store connectors attached to the Gemini Enterprise engine
(Google Drive, and any connector added later via the UI) with a single API call.

How it works:
  - Each connector added in the Gemini Enterprise UI creates a data store under
    the same engine (stratova-gemini_1779267526762).
  - Querying the engine's serving config searches across *all* attached data
    stores automatically — no code changes required when new connectors are added.

Config (tools_config.json):
  "gemini_connectors": {
    "enabled": true,
    "config": {
      "project_id": "ninth-archway-496404-s2",
      "project_number": "528271267622",
      "engine_id": "stratova-gemini_1779267526762",
      "location": "global",
      "max_results": 10
    }
  }
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)

_DISCOVERY_ENGINE_BASE = "https://discoveryengine.googleapis.com/v1"


def _get_access_token() -> str:
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _search(cfg: dict, query: str, max_results: int) -> list[dict]:
    import requests

    project_id = cfg.get("project_id", "")
    engine_id = cfg.get("engine_id", "")
    location = cfg.get("location", "global")

    url = (
        f"{_DISCOVERY_ENGINE_BASE}/projects/{project_id}/locations/{location}"
        f"/collections/default_collection/engines/{engine_id}"
        f"/servingConfigs/default_search:search"
    )
    headers = {
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": project_id,
    }
    body = {
        "query": query,
        "pageSize": max_results,
        "queryExpansionSpec": {"condition": "AUTO"},
        "spellCorrectionSpec": {"mode": "AUTO"},
        "contentSearchSpec": {
            "snippetSpec": {"returnSnippet": True, "maxSnippetCount": 3},
            "extractiveContentSpec": {"maxExtractiveAnswerCount": 2},
        },
    }
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json().get("results", [])


def _format_results(raw_results: list[dict]) -> list[dict]:
    out = []
    for r in raw_results:
        doc = r.get("document", {})
        derived = doc.get("derivedStructData", {})
        struct_data = doc.get("structData", {})

        # Title — try multiple field paths
        title = (
            derived.get("title")
            or struct_data.get("title")
            or derived.get("filename")
            or doc.get("id", "")
        )

        # Link / source URL
        link = (
            derived.get("link")
            or derived.get("uri")
            or struct_data.get("url")
            or ""
        )

        # Data source connector type
        source = derived.get("datasource_type") or derived.get("source") or "connector"

        # Snippet text
        snippets = []
        for s in derived.get("snippets", []):
            text = s.get("snippet") or s.get("snippetStatus", "")
            if text and text != "NO_SNIPPET_AVAILABLE":
                snippets.append(text)

        # Extractive answers (richer content)
        answers = []
        for a in derived.get("extractive_answers", []):
            content = a.get("content", "")
            if content:
                answers.append(content)

        out.append({
            "title": title,
            "source": source,
            "link": link,
            "snippet": " ".join(snippets[:2]) if snippets else "",
            "content": " ".join(answers[:2]) if answers else "",
        })
    return out


def get_tools() -> list[Callable]:
    def search_gemini_connectors(query: str, max_results: int = 10) -> dict:
        """Search across all Gemini Enterprise connectors (Google Drive, and any future connectors).

        This searches ALL data sources connected via the Gemini Enterprise UI —
        including Google Drive, and any connector added in the future — with a
        single query. No reconfiguration needed when new connectors are added.

        Use this tool when the user asks about files, documents, or information
        that may be stored in connected company data sources (Drive, SharePoint
        via Gemini Enterprise, etc.).

        Args:
            query: Natural language or keyword search query.
            max_results: Maximum number of results to return (default 10, max 25).

        Returns:
            dict with a list of matching documents including title, source,
            link, snippet, and extracted content.
        """
        cfg = get_config().tools.get("gemini_connectors")
        if not cfg or not cfg.enabled:
            return {
                "status": "disabled",
                "message": "Gemini Enterprise connector search is currently disabled.",
            }
        max_results = min(max_results, 25)
        try:
            raw = _search(cfg.config, query, max_results)
            results = _format_results(raw)
            return {
                "results": results,
                "count": len(results),
                "query": query,
            }
        except Exception as exc:
            logger.error("Gemini connector search error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [search_gemini_connectors]
