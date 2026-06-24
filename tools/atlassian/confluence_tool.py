"""Confluence tool — Atlassian Cloud REST API via atlassian-python-api.

Required credentials (set in tools_config.json or env vars):
  url        : https://your-org.atlassian.net/wiki
  username   : your-admin@your-org.com
  api_token  : Atlassian API token (create at id.atlassian.com → Security)

In tools_config.json, reference secrets as:
  "api_token": "env:CONFLUENCE_API_TOKEN"
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)

_MAX_CONTENT_CHARS = 50_000


def _confluence(cfg: dict):
    from atlassian import Confluence

    return Confluence(
        url=cfg.get("url", ""),
        username=cfg.get("username", ""),
        password=cfg.get("api_token", ""),
        cloud=True,
    )


def get_tools() -> list[Callable]:
    def search_confluence(query: str, space_key: str = "", max_results: int = 10) -> dict:
        """Search Confluence pages and documentation spaces.

        Use this tool to find internal runbooks, architecture docs, how-to guides,
        and wiki pages stored in Confluence.

        Args:
            query: Full-text search query (keywords or phrases).
            space_key: Optional Confluence space key to restrict search (e.g. 'ENG', 'OPS').
                       Leave blank to search all spaces.
            max_results: Maximum number of pages to return (default 10).

        Returns:
            dict with a list of matching pages (id, title, space, URL, excerpt).
        """
        cfg = get_config().tools.get("confluence")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Confluence tool is currently disabled."}
        try:
            conf = _confluence(cfg.config)
            cql = f'text ~ "{query}" AND type = page'
            if space_key:
                cql += f' AND space = "{space_key}"'
            base_url = cfg.config.get("url", "").rstrip("/")
            results = conf.cql(cql, limit=max_results)
            pages = []
            for r in results.get("results", []):
                relative = r.get("url", "")
                full_url = (base_url + relative) if relative.startswith("/") else relative
                pages.append(
                    {
                        "id": r["content"]["id"],
                        "title": r["content"]["title"],
                        "space": r.get("resultGlobalContainer", {}).get("title", ""),
                        "url": full_url,
                        "excerpt": r.get("excerpt", ""),
                    }
                )
            return {"pages": pages, "count": len(pages)}
        except Exception as exc:
            logger.error("Confluence search error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_confluence_page(page_id: str) -> dict:
        """Get the full text content of a Confluence page.

        Use this after search_confluence to read the complete content of a specific page.
        HTML markup is stripped; only plain text is returned.

        Args:
            page_id: Confluence page ID returned by search_confluence.

        Returns:
            dict with page title, space name, and full plain-text content.
        """
        cfg = get_config().tools.get("confluence")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Confluence tool is currently disabled."}
        try:
            from bs4 import BeautifulSoup

            conf = _confluence(cfg.config)
            page = conf.get_page_by_id(page_id, expand="body.storage,space")
            html = page.get("body", {}).get("storage", {}).get("value", "")
            text = BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)
            return {
                "id": page_id,
                "title": page.get("title", ""),
                "space": page.get("space", {}).get("name", ""),
                "content": text[:_MAX_CONTENT_CHARS],
            }
        except Exception as exc:
            logger.error("Confluence get_page error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [search_confluence, get_confluence_page]
