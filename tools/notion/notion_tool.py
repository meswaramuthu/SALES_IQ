"""Notion tool — Notion REST API v1 integration.

Required credentials (set in tools_config.json or env vars):
  api_token : Notion integration token (create at https://www.notion.so/my-integrations)

In tools_config.json, reference secrets as:
  "api_token": "env:NOTION_API_TOKEN"

Note: The integration must be connected to each workspace page it needs to access.
      Open the page in Notion → ··· menu → Add connections → select your integration.

Tools exported:
  search_notion          - full-text search across all connected pages and databases
  get_notion_page        - get the plain-text content of a Notion page
  list_notion_databases  - list all accessible Notion databases
  query_notion_database  - query rows/records from a Notion database
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)

_NOTION_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_MAX_CONTENT_CHARS = 50_000


def _session(api_token: str):
    import requests
    sess = requests.Session()
    sess.headers.update({
        "Authorization": f"Bearer {api_token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    })
    return sess


def _blocks_to_text(sess, block_id: str, depth: int = 0) -> str:
    """Recursively convert Notion blocks to plain text."""
    if depth > 3:
        return ""
    try:
        resp = sess.get(f"{_NOTION_BASE}/blocks/{block_id}/children", timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return ""

    lines: list[str] = []
    for block in data.get("results", []):
        btype = block.get("type", "")
        content = block.get(btype, {})

        rich_texts = content.get("rich_text", [])
        text = "".join(rt.get("plain_text", "") for rt in rich_texts)

        prefix = ""
        if btype == "bulleted_list_item":
            prefix = "• "
        elif btype == "numbered_list_item":
            prefix = "1. "
        elif btype == "to_do":
            checked = content.get("checked", False)
            prefix = "[x] " if checked else "[ ] "
        elif btype.startswith("heading_"):
            level = int(btype[-1])
            prefix = "#" * level + " "
        elif btype == "quote":
            prefix = "> "
        elif btype == "code":
            lang = content.get("language", "")
            text = f"```{lang}\n{text}\n```"
        elif btype == "divider":
            lines.append("---")
            continue
        elif btype in ("child_page", "child_database"):
            title = content.get("title", "")
            lines.append(f"[{btype.replace('_', ' ').title()}: {title}]")
            continue
        elif btype == "image":
            url = (
                content.get("file", {}).get("url", "")
                or content.get("external", {}).get("url", "")
            )
            caption = "".join(rt.get("plain_text", "") for rt in content.get("caption", []))
            lines.append(f"[Image: {caption or url}]")
            continue

        if text:
            lines.append(f"{prefix}{text}")

        if block.get("has_children") and btype not in ("child_page", "child_database"):
            child_text = _blocks_to_text(sess, block["id"], depth + 1)
            if child_text:
                indented = "\n".join("  " + ln for ln in child_text.splitlines())
                lines.append(indented)

    return "\n".join(lines)


def _page_title(page: dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(rt.get("plain_text", "") for rt in prop.get("title", []))
    return page.get("url", "")


def get_tools() -> list[Callable]:

    def search_notion(query: str, filter_type: str = "all", max_results: int = 10) -> dict:
        """Search across all Notion pages and databases the integration has access to.

        Use this as the starting point to find any content in Notion — wiki pages,
        project docs, meeting notes, roadmaps, or database records.

        Args:
            query: Search query — keywords or phrases to find in page titles and content.
            filter_type: What to search. One of:
                         'all'      — pages and databases (default)
                         'page'     — wiki pages and docs only
                         'database' — databases (structured data) only
            max_results: Maximum results to return (default 10, max 100).

        Returns:
            dict with a list of results (id, title, type, url, last_edited).
        """
        cfg = get_config().tools.get("notion")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Notion tool is currently disabled."}
        try:
            sess = _session(cfg.config.get("api_token", ""))
            body: dict = {"query": query, "page_size": min(max_results, 100)}
            if filter_type in ("page", "database"):
                body["filter"] = {"value": filter_type, "property": "object"}
            resp = sess.post(f"{_NOTION_BASE}/search", json=body, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for obj in data.get("results", []):
                otype = obj.get("object", "")
                title = _page_title(obj) if otype == "page" else obj.get("title", [{}])
                if isinstance(title, list):
                    title = "".join(rt.get("plain_text", "") for rt in title)
                results.append({
                    "id": obj.get("id", ""),
                    "title": title,
                    "type": otype,
                    "url": obj.get("url", ""),
                    "last_edited": obj.get("last_edited_time", ""),
                })
            return {"results": results, "count": len(results)}
        except Exception as exc:
            logger.error("search_notion error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_notion_page(page_id: str) -> dict:
        """Get the full plain-text content of a Notion page.

        Use this after search_notion to read the complete content of a specific page.
        All blocks (paragraphs, headings, bullets, code, tables) are converted to text.

        Args:
            page_id: Notion page ID from search_notion results.

        Returns:
            dict with title, url, last_edited, content (plain text), and truncated flag.
        """
        cfg = get_config().tools.get("notion")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Notion tool is currently disabled."}
        try:
            sess = _session(cfg.config.get("api_token", ""))
            resp = sess.get(f"{_NOTION_BASE}/pages/{page_id}", timeout=20)
            resp.raise_for_status()
            page = resp.json()
            title = _page_title(page)
            url = page.get("url", "")
            last_edited = page.get("last_edited_time", "")
            content = _blocks_to_text(sess, page_id)
            return {
                "id": page_id,
                "title": title,
                "url": url,
                "last_edited": last_edited,
                "content": content[:_MAX_CONTENT_CHARS],
                "truncated": len(content) > _MAX_CONTENT_CHARS,
            }
        except Exception as exc:
            logger.error("get_notion_page error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_notion_databases(max_results: int = 20) -> dict:
        """List all Notion databases the integration has access to.

        Use this to discover available structured data sources in Notion —
        project trackers, CRM records, task boards, content calendars, etc.

        Args:
            max_results: Maximum databases to return (default 20).

        Returns:
            dict with a list of databases (id, title, url, last_edited, properties).
        """
        cfg = get_config().tools.get("notion")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Notion tool is currently disabled."}
        try:
            sess = _session(cfg.config.get("api_token", ""))
            body = {
                "filter": {"value": "database", "property": "object"},
                "page_size": min(max_results, 100),
            }
            resp = sess.post(f"{_NOTION_BASE}/search", json=body, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            databases = []
            for db in data.get("results", []):
                title_parts = db.get("title", [])
                title = "".join(rt.get("plain_text", "") for rt in title_parts)
                props = {
                    k: v.get("type", "") for k, v in db.get("properties", {}).items()
                }
                databases.append({
                    "id": db.get("id", ""),
                    "title": title,
                    "url": db.get("url", ""),
                    "last_edited": db.get("last_edited_time", ""),
                    "properties": props,
                })
            return {"databases": databases, "count": len(databases)}
        except Exception as exc:
            logger.error("list_notion_databases error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def query_notion_database(
        database_id: str,
        filter_json: str = "",
        sorts_json: str = "",
        max_results: int = 20,
    ) -> dict:
        """Query records from a Notion database with optional filtering and sorting.

        Use this after list_notion_databases to read structured records — tasks,
        projects, contacts, issues, or any other data stored in a Notion database.

        Args:
            database_id: Database ID from list_notion_databases.
            filter_json: Optional JSON string for Notion filter object, e.g.:
                         '{"property": "Status", "select": {"equals": "In Progress"}}'
                         Leave blank to return all records.
            sorts_json:  Optional JSON string for sort array, e.g.:
                         '[{"property": "Due Date", "direction": "ascending"}]'
            max_results: Maximum records to return (default 20, max 100).

        Returns:
            dict with list of records, each containing id, url, last_edited,
            and all property values as plain text.
        """
        cfg = get_config().tools.get("notion")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Notion tool is currently disabled."}
        try:
            import json as _json
            sess = _session(cfg.config.get("api_token", ""))
            body: dict = {"page_size": min(max_results, 100)}
            if filter_json:
                body["filter"] = _json.loads(filter_json)
            if sorts_json:
                body["sorts"] = _json.loads(sorts_json)
            resp = sess.post(
                f"{_NOTION_BASE}/databases/{database_id}/query",
                json=body,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            records = []
            for page in data.get("results", []):
                props_raw = page.get("properties", {})
                props: dict[str, str] = {}
                for name, prop in props_raw.items():
                    ptype = prop.get("type", "")
                    val = prop.get(ptype, "")
                    if ptype == "title":
                        props[name] = "".join(rt.get("plain_text", "") for rt in (val or []))
                    elif ptype == "rich_text":
                        props[name] = "".join(rt.get("plain_text", "") for rt in (val or []))
                    elif ptype == "select":
                        props[name] = (val or {}).get("name", "")
                    elif ptype == "multi_select":
                        props[name] = ", ".join(opt.get("name", "") for opt in (val or []))
                    elif ptype == "status":
                        props[name] = (val or {}).get("name", "")
                    elif ptype == "date":
                        props[name] = (val or {}).get("start", "") if val else ""
                    elif ptype == "checkbox":
                        props[name] = str(val)
                    elif ptype in ("number", "url", "email", "phone_number"):
                        props[name] = str(val) if val is not None else ""
                    elif ptype == "people":
                        props[name] = ", ".join(
                            p.get("name", "") for p in (val or [])
                        )
                    elif ptype == "relation":
                        props[name] = f"{len(val or [])} related items"
                    else:
                        props[name] = str(val) if val else ""
                records.append({
                    "id": page.get("id", ""),
                    "url": page.get("url", ""),
                    "last_edited": page.get("last_edited_time", ""),
                    "properties": props,
                })
            return {
                "records": records,
                "count": len(records),
                "has_more": data.get("has_more", False),
                "database_id": database_id,
            }
        except Exception as exc:
            logger.error("query_notion_database error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [search_notion, get_notion_page, list_notion_databases, query_notion_database]
