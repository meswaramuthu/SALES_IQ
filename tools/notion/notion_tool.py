"""Notion tool — Notion REST API v1 integration.

Required credentials (set in tools_config.json or env vars):
  api_token : Notion integration token (create at https://www.notion.so/my-integrations)

In tools_config.json, reference secrets as:
  "api_token": "env:NOTION_API_TOKEN"

Note: The integration must be connected to each workspace page it needs to access.
      Open the page in Notion → ··· menu → Add connections → select your integration.

Tools exported:
  READ
    search_notion            - full-text search across all connected pages and databases
    get_notion_page          - get the plain-text content of a Notion page
    list_notion_databases    - list all accessible Notion databases
    query_notion_database    - query rows/records from a Notion database

  CREATE
    create_notion_page       - create a new page under a parent page or database
    create_notion_database_row - add a new row/record to a Notion database
    append_notion_blocks     - append content blocks to an existing page

  UPDATE
    update_notion_page       - update page title and/or properties

  DELETE (soft)
    archive_notion_page      - archive (soft-delete) a page or database row
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


def _rich_text(text: str) -> list[dict]:
    """Build a Notion rich_text array from plain text."""
    return [{"type": "text", "text": {"content": text}}]


def _is_notion_id(val: str) -> bool:
    """Return True if val looks like a Notion UUID (32 hex chars, optionally hyphenated)."""
    import re
    return bool(re.match(
        r'^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$',
        val.strip(), re.IGNORECASE,
    ))


def _resolve_notion_page(sess, page_id_or_title: str) -> "str | dict":
    """Resolve a Notion page title or UUID to a page ID.

    Returns the page ID string on success, or an error/needs_clarification dict.
    """
    val = page_id_or_title.strip()
    if _is_notion_id(val):
        return val
    try:
        body = {"query": val, "filter": {"value": "page", "property": "object"}, "page_size": 6}
        resp = sess.post(f"{_NOTION_BASE}/search", json=body, timeout=20)
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as exc:
        return {"status": "error", "message": f"Failed to search Notion for '{val}': {exc}"}
    if not results:
        return {"status": "error", "message": f"No Notion page found matching '{val}'."}
    if len(results) == 1:
        return results[0]["id"]
    options = [
        {"id": r["id"], "title": _page_title(r), "url": r.get("url", ""), "last_edited": r.get("last_edited_time", "")}
        for r in results[:5]
    ]
    return {
        "status": "needs_clarification",
        "message": f"Multiple Notion pages match '{val}'. Please ask the user to pick one:",
        "options": options,
    }


def _resolve_notion_database(sess, db_id_or_name: str) -> "str | dict":
    """Resolve a Notion database name or UUID to a database ID.

    Returns the database ID string on success, or an error/needs_clarification dict.
    """
    val = db_id_or_name.strip()
    if _is_notion_id(val):
        return val
    try:
        body = {"query": val, "filter": {"value": "database", "property": "object"}, "page_size": 6}
        resp = sess.post(f"{_NOTION_BASE}/search", json=body, timeout=20)
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as exc:
        return {"status": "error", "message": f"Failed to search Notion databases for '{val}': {exc}"}
    if not results:
        return {"status": "error", "message": f"No Notion database found matching '{val}'."}
    if len(results) == 1:
        return results[0]["id"]
    options = [
        {
            "id": r["id"],
            "title": "".join(t.get("plain_text", "") for t in r.get("title", [])),
            "url": r.get("url", ""),
        }
        for r in results[:5]
    ]
    return {
        "status": "needs_clarification",
        "message": f"Multiple Notion databases match '{val}'. Please ask the user to pick one:",
        "options": options,
    }


def _markdown_to_blocks(text: str) -> list[dict]:
    """Convert plain text (with basic markdown) to Notion block objects."""
    blocks = []
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.startswith("# "):
            blocks.append({"type": "heading_1", "heading_1": {"rich_text": _rich_text(stripped[2:])}})
        elif stripped.startswith("## "):
            blocks.append({"type": "heading_2", "heading_2": {"rich_text": _rich_text(stripped[3:])}})
        elif stripped.startswith("### "):
            blocks.append({"type": "heading_3", "heading_3": {"rich_text": _rich_text(stripped[4:])}})
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append({"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rich_text(stripped[2:])}})
        elif stripped.startswith("1. "):
            blocks.append({"type": "numbered_list_item", "numbered_list_item": {"rich_text": _rich_text(stripped[3:])}})
        elif stripped == "---":
            blocks.append({"type": "divider", "divider": {}})
        elif stripped:
            blocks.append({"type": "paragraph", "paragraph": {"rich_text": _rich_text(stripped)}})
        else:
            blocks.append({"type": "paragraph", "paragraph": {"rich_text": []}})
    return blocks


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

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

        Accepts either a Notion page UUID or a page title string — the title is
        resolved to an ID automatically. If multiple pages match, the options are
        returned for the user to choose from.

        Args:
            page_id: Notion page UUID or page title string.

        Returns:
            dict with title, url, last_edited, content (plain text), and truncated flag.
        """
        cfg = get_config().tools.get("notion")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Notion tool is currently disabled."}
        try:
            sess = _session(cfg.config.get("api_token", ""))
            resolved = _resolve_notion_page(sess, page_id)
            if isinstance(resolved, dict):
                return resolved
            page_id = resolved
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

        Accepts either a Notion database UUID or a database name — the name is
        resolved to an ID automatically. If multiple databases match, the options
        are returned for the user to choose from.

        Args:
            database_id: Notion database UUID or database name (e.g. 'Tasks', 'CRM').
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
            resolved = _resolve_notion_database(sess, database_id)
            if isinstance(resolved, dict):
                return resolved
            database_id = resolved
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

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_notion_page(
        title: str,
        parent_page_id: str = "",
        parent_database_id: str = "",
        content: str = "",
        title_property_name: str = "title",
    ) -> dict:
        """Create a new Notion page under a parent page or database.

        Provide either parent_page_id (for a wiki-style sub-page) or
        parent_database_id (to add a record to a database). Exactly one
        of the two parent fields must be supplied.

        Both parent fields accept a Notion UUID or a human-readable title/name
        — they are resolved to IDs automatically. If multiple items match,
        the options are returned for the user to choose from.

        Args:
            title: Page title.
            parent_page_id: UUID or title of the parent Notion page. Mutually
                            exclusive with parent_database_id.
            parent_database_id: UUID or name of the parent Notion database.
                                 Mutually exclusive with parent_page_id.
            content: Optional page body as plain text or simple markdown
                     (headings with #/##/###, bullets with - or *, numbered
                     lists with 1., dividers with ---). Leave blank for an
                     empty page.
            title_property_name: Name of the title property in the database.
                                  For standalone pages this is always "title".
                                  For database rows the title column may be
                                  named "Name", "Task", etc. — check
                                  list_notion_databases to find the right name.
                                  Defaults to "title".

        Returns:
            dict with page id, title, url, and created status.
        """
        cfg = get_config().tools.get("notion")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Notion tool is currently disabled."}
        if not parent_page_id and not parent_database_id:
            return {"status": "error", "message": "Provide either parent_page_id or parent_database_id."}
        if parent_page_id and parent_database_id:
            return {"status": "error", "message": "Provide only one of parent_page_id or parent_database_id."}
        try:
            sess = _session(cfg.config.get("api_token", ""))
            if parent_page_id:
                resolved = _resolve_notion_page(sess, parent_page_id)
                if isinstance(resolved, dict):
                    return resolved
                parent = {"type": "page_id", "page_id": resolved}
            else:
                resolved = _resolve_notion_database(sess, parent_database_id)
                if isinstance(resolved, dict):
                    return resolved
                parent = {"type": "database_id", "database_id": resolved}

            body: dict = {
                "parent": parent,
                "properties": {
                    title_property_name: {"title": _rich_text(title)},
                },
            }
            if content:
                body["children"] = _markdown_to_blocks(content)

            resp = sess.post(f"{_NOTION_BASE}/pages", json=body, timeout=30)
            resp.raise_for_status()
            page = resp.json()
            return {
                "id": page.get("id", ""),
                "title": title,
                "url": page.get("url", ""),
                "status": "created",
            }
        except Exception as exc:
            logger.error("create_notion_page error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_notion_database_row(
        database_id: str,
        properties_json: str,
    ) -> dict:
        """Add a new row (record) to a Notion database.

        Use list_notion_databases to discover property names and types before
        calling this tool. The database_id accepts a UUID or a database name
        — the name is resolved automatically.

        Args:
            database_id: Notion database UUID or database name (e.g. 'Tasks', 'CRM').
            properties_json: JSON string of Notion property objects in the
                             Notion API format. Examples:
                             For a title property named "Name":
                               '{"Name": {"title": [{"text": {"content": "My task"}}]}}'
                             For status + date:
                               '{"Status": {"select": {"name": "In Progress"}},
                                 "Due": {"date": {"start": "2026-07-01"}}}'

        Returns:
            dict with new row id, url, and created status.
        """
        cfg = get_config().tools.get("notion")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Notion tool is currently disabled."}
        try:
            import json as _json
            sess = _session(cfg.config.get("api_token", ""))
            resolved = _resolve_notion_database(sess, database_id)
            if isinstance(resolved, dict):
                return resolved
            database_id = resolved
            props = _json.loads(properties_json)
            body = {
                "parent": {"database_id": database_id},
                "properties": props,
            }
            resp = sess.post(f"{_NOTION_BASE}/pages", json=body, timeout=30)
            resp.raise_for_status()
            page = resp.json()
            return {
                "id": page.get("id", ""),
                "url": page.get("url", ""),
                "database_id": database_id,
                "status": "created",
            }
        except Exception as exc:
            logger.error("create_notion_database_row error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def append_notion_blocks(page_id: str, content: str) -> dict:
        """Append content blocks to an existing Notion page.

        Use this to add new paragraphs, bullet points, headings, or other
        content at the end of a page without replacing existing content.
        Accepts a page UUID or a page title — resolved automatically.

        Args:
            page_id: Notion page UUID or page title string.
            content: Text to append as plain text or simple markdown.
                     Headings: # H1, ## H2, ### H3
                     Bullets: - item or * item
                     Numbered: 1. item
                     Dividers: ---
                     Any other line becomes a paragraph.

        Returns:
            dict confirming the blocks were appended.
        """
        cfg = get_config().tools.get("notion")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Notion tool is currently disabled."}
        if not content.strip():
            return {"status": "error", "message": "content must not be empty."}
        try:
            sess = _session(cfg.config.get("api_token", ""))
            resolved = _resolve_notion_page(sess, page_id)
            if isinstance(resolved, dict):
                return resolved
            page_id = resolved
            blocks = _markdown_to_blocks(content)
            resp = sess.patch(
                f"{_NOTION_BASE}/blocks/{page_id}/children",
                json={"children": blocks},
                timeout=30,
            )
            resp.raise_for_status()
            return {
                "page_id": page_id,
                "blocks_appended": len(blocks),
                "status": "appended",
            }
        except Exception as exc:
            logger.error("append_notion_blocks error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_notion_page(
        page_id: str,
        title: str = "",
        properties_json: str = "",
        title_property_name: str = "title",
    ) -> dict:
        """Update the title and/or properties of a Notion page or database row.

        For simple page title changes, supply only title. For database rows
        with multiple properties, supply properties_json in Notion API format.
        Accepts a page UUID or a page title — resolved automatically.

        Args:
            page_id: Notion page UUID or page title string.
            title: New page title. Leave blank to keep the existing title.
            properties_json: JSON string of Notion property objects to update.
                             Uses Notion API format (same as create_notion_database_row).
                             Leave blank if only updating the title.
            title_property_name: Name of the title property. For standalone pages
                                  use "title" (default). For database rows check
                                  list_notion_databases for the correct column name
                                  (e.g. "Name", "Task").

        Returns:
            dict with updated page id, url, and status.
        """
        cfg = get_config().tools.get("notion")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Notion tool is currently disabled."}
        if not title and not properties_json:
            return {"status": "error", "message": "Provide at least title or properties_json to update."}
        try:
            import json as _json
            sess = _session(cfg.config.get("api_token", ""))
            resolved = _resolve_notion_page(sess, page_id)
            if isinstance(resolved, dict):
                return resolved
            page_id = resolved
            props: dict = {}
            if title:
                props[title_property_name] = {"title": _rich_text(title)}
            if properties_json:
                props.update(_json.loads(properties_json))

            resp = sess.patch(
                f"{_NOTION_BASE}/pages/{page_id}",
                json={"properties": props},
                timeout=20,
            )
            resp.raise_for_status()
            page = resp.json()
            return {
                "id": page_id,
                "url": page.get("url", ""),
                "status": "updated",
            }
        except Exception as exc:
            logger.error("update_notion_page error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE (soft) ─────────────────────────────────────────────────────────

    def archive_notion_page(page_id: str) -> dict:
        """Archive (soft-delete) a Notion page or database row.

        The page is archived and hidden from searches but not permanently
        deleted — it can be restored from the Notion trash.
        Accepts a page UUID or a page title — resolved automatically.

        Args:
            page_id: Notion page UUID or page title string.

        Returns:
            dict confirming the archive.
        """
        cfg = get_config().tools.get("notion")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Notion tool is currently disabled."}
        try:
            sess = _session(cfg.config.get("api_token", ""))
            resolved = _resolve_notion_page(sess, page_id)
            if isinstance(resolved, dict):
                return resolved
            page_id = resolved
            resp = sess.patch(
                f"{_NOTION_BASE}/pages/{page_id}",
                json={"archived": True},
                timeout=20,
            )
            resp.raise_for_status()
            return {"id": page_id, "status": "archived"}
        except Exception as exc:
            logger.error("archive_notion_page error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        search_notion,
        get_notion_page,
        list_notion_databases,
        query_notion_database,
        # Create
        create_notion_page,
        create_notion_database_row,
        append_notion_blocks,
        # Update
        update_notion_page,
        # Delete (soft)
        archive_notion_page,
    ]
