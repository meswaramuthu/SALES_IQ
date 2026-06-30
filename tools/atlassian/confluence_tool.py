"""Confluence tool — Atlassian Cloud REST API via atlassian-python-api.

Required credentials (set in tools_config.json or env vars):
  url        : https://your-org.atlassian.net/wiki
  username   : your-admin@your-org.com
  api_token  : Atlassian API token (create at id.atlassian.com → Security)

In tools_config.json, reference secrets as:
  "api_token": "env:CONFLUENCE_API_TOKEN"

Tools exported:
  READ
    search_confluence        - full-text search across Confluence spaces
    get_confluence_page      - get full plain-text content of a page

  CREATE
    create_confluence_page   - create a new page in a space
    add_confluence_comment   - post a comment on a page

  UPDATE
    update_confluence_page   - update title and/or content of a page

  DELETE
    delete_confluence_page   - move a page to trash
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)

_MAX_CONTENT_CHARS = 50_000


def _resolve_page(conf, page_id_or_title: str, base_url: str = "") -> "str | dict":
    """Resolve a Confluence page ID (numeric string) or title to a page ID.

    Returns the page ID string on success, or an error/needs_clarification dict.
    """
    val = page_id_or_title.strip()
    if val.isdigit():
        return val
    pages: list = []
    for cql in (
        f'title = "{val}" AND type = page',
        f'title ~ "{val}" AND type = page',
    ):
        try:
            results = conf.cql(cql, limit=6)
            pages = results.get("results", [])
            if pages:
                break
        except Exception:
            pages = []
    if not pages:
        return {"status": "error", "message": f"No Confluence page found matching '{val}'."}
    if len(pages) == 1:
        return pages[0]["content"]["id"]
    options = []
    for p in pages[:5]:
        raw_url = p.get("url", "")
        full_url = (base_url + raw_url) if raw_url.startswith("/") else raw_url
        options.append({
            "id": p["content"]["id"],
            "title": p["content"]["title"],
            "space": p.get("resultGlobalContainer", {}).get("title", ""),
            "url": full_url,
        })
    return {
        "status": "needs_clarification",
        "message": f"Multiple Confluence pages match '{val}'. Please ask the user to pick one:",
        "options": options,
    }


def _confluence(cfg: dict):
    from atlassian import Confluence

    return Confluence(
        url=cfg.get("url", ""),
        username=cfg.get("username", ""),
        password=cfg.get("api_token", ""),
        cloud=True,
    )


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

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

        Accepts either a numeric page ID (from search_confluence) or a page title
        string — the title is resolved to an ID automatically. If multiple pages
        match the title, the options are returned for the user to choose from.

        Args:
            page_id: Confluence page ID (numeric) or page title string.

        Returns:
            dict with page title, space name, and full plain-text content.
        """
        cfg = get_config().tools.get("confluence")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Confluence tool is currently disabled."}
        try:
            from bs4 import BeautifulSoup

            conf = _confluence(cfg.config)
            base_url = cfg.config.get("url", "").rstrip("/")
            resolved = _resolve_page(conf, page_id, base_url)
            if isinstance(resolved, dict):
                return resolved
            page_id = resolved
            page = conf.get_page_by_id(page_id, expand="body.storage,space,version")
            html = page.get("body", {}).get("storage", {}).get("value", "")
            text = BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)
            return {
                "id": page_id,
                "title": page.get("title", ""),
                "space": page.get("space", {}).get("name", ""),
                "version": page.get("version", {}).get("number", 1),
                "content": text[:_MAX_CONTENT_CHARS],
            }
        except Exception as exc:
            logger.error("Confluence get_page error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_confluence_page(
        space_key: str,
        title: str,
        body: str = "",
        parent_id: str = "",
    ) -> dict:
        """Create a new Confluence page in a space.

        Args:
            space_key: Confluence space key where the page will be created
                       (e.g. 'ENG', 'OPS', 'WIKI'). Use search_confluence to
                       discover space keys.
            title: Page title. Must be unique within the space.
            body: Page content in plain text or Confluence wiki markup.
                  Leave blank to create an empty page.
            parent_id: Optional parent page — accepts a numeric page ID or a
                       page title string (resolved automatically). Leave blank
                       to create the page at the root of the space.

        Returns:
            dict with created page id, title, space, and URL.
        """
        cfg = get_config().tools.get("confluence")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Confluence tool is currently disabled."}
        try:
            conf = _confluence(cfg.config)
            base_url = cfg.config.get("url", "").rstrip("/")
            resolved_parent = None
            if parent_id:
                resolved = _resolve_page(conf, parent_id, base_url)
                if isinstance(resolved, dict):
                    return resolved
                resolved_parent = resolved
            result = conf.create_page(
                space=space_key,
                title=title,
                body=body,
                parent_id=resolved_parent,
                representation="wiki",
            )
            page_id = result.get("id", "")
            base_url = cfg.config.get("url", "").rstrip("/")
            links = result.get("_links", {})
            web_url = base_url + links.get("webui", f"/wiki/spaces/{space_key}/pages/{page_id}")
            return {
                "id": page_id,
                "title": result.get("title", title),
                "space": space_key,
                "url": web_url,
                "status": "created",
            }
        except Exception as exc:
            logger.error("Confluence create_page error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_confluence_comment(page_id: str, body: str) -> dict:
        """Add a comment to a Confluence page.

        Args:
            page_id: Confluence page ID (numeric) or page title string — the
                     title is resolved to an ID automatically.
            body: Comment text to post.

        Returns:
            dict with comment id and status confirming the post.
        """
        cfg = get_config().tools.get("confluence")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Confluence tool is currently disabled."}
        try:
            conf = _confluence(cfg.config)
            base_url = cfg.config.get("url", "").rstrip("/")
            resolved = _resolve_page(conf, page_id, base_url)
            if isinstance(resolved, dict):
                return resolved
            page_id = resolved
            result = conf.add_comment(page_id, body)
            return {
                "comment_id": result.get("id", ""),
                "page_id": page_id,
                "status": "commented",
            }
        except Exception as exc:
            logger.error("Confluence add_comment error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_confluence_page(
        page_id: str,
        title: str = "",
        body: str = "",
        version_comment: str = "",
    ) -> dict:
        """Update the title and/or content of a Confluence page.

        Retrieves the current page version automatically and increments it.
        Only the fields you supply are changed.

        Args:
            page_id: Confluence page ID (numeric) or page title string — the
                     title is resolved to an ID automatically.
            title: New page title. Leave blank to keep the existing title.
            body: New page content in Confluence wiki markup or plain text.
                  Leave blank to keep the existing content.
            version_comment: Optional comment to attach to this version/edit.

        Returns:
            dict with updated page id, title, new version number, and URL.
        """
        cfg = get_config().tools.get("confluence")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Confluence tool is currently disabled."}
        if not title and not body:
            return {"status": "error", "message": "Provide at least title or body to update."}
        try:
            conf = _confluence(cfg.config)
            base_url = cfg.config.get("url", "").rstrip("/")
            resolved = _resolve_page(conf, page_id, base_url)
            if isinstance(resolved, dict):
                return resolved
            page_id = resolved
            page = conf.get_page_by_id(page_id, expand="body.storage,version")
            current_title = page.get("title", "")
            current_body = page.get("body", {}).get("storage", {}).get("value", "")

            new_title = title or current_title
            new_body = body if body else current_body

            result = conf.update_page(
                page_id=page_id,
                title=new_title,
                body=new_body,
                representation="wiki" if body else "storage",
                version_comment=version_comment,
            )
            new_version = result.get("version", {}).get("number", "")
            base_url = cfg.config.get("url", "").rstrip("/")
            links = result.get("_links", {})
            web_url = base_url + links.get("webui", f"/wiki/pages/{page_id}")
            return {
                "id": page_id,
                "title": new_title,
                "version": new_version,
                "url": web_url,
                "status": "updated",
            }
        except Exception as exc:
            logger.error("Confluence update_page error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_confluence_page(page_id: str) -> dict:
        """Move a Confluence page to trash.

        The page is moved to the Confluence trash and can be restored by an
        admin. It is not permanently removed immediately.

        Args:
            page_id: Confluence page ID (numeric) or page title string — the
                     title is resolved to an ID automatically.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("confluence")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Confluence tool is currently disabled."}
        try:
            conf = _confluence(cfg.config)
            base_url = cfg.config.get("url", "").rstrip("/")
            resolved = _resolve_page(conf, page_id, base_url)
            if isinstance(resolved, dict):
                return resolved
            page_id = resolved
            conf.remove_page(page_id)
            return {"id": page_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Confluence delete_page error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        search_confluence,
        get_confluence_page,
        # Create
        create_confluence_page,
        add_confluence_comment,
        # Update
        update_confluence_page,
        # Delete
        delete_confluence_page,
    ]
