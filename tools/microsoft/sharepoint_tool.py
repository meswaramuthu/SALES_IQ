"""SharePoint tool — Microsoft Graph API v1.0 integration.

Required credentials (set in tools_config.json or env vars):
  tenant_id     : Azure AD tenant ID (Directory ID)
  client_id     : App registration client ID
  client_secret : App registration client secret (use env:SHAREPOINT_CLIENT_SECRET)
  site_url      : Default SharePoint site URL
                  (e.g. https://contoso.sharepoint.com/sites/Engineering)
                  Optional — used as fallback when site_id is not specified.

Azure AD app registration requirements:
  Permission type : Application (not Delegated)
  Permissions     : Sites.ReadWrite.All, Files.ReadWrite.All
                    (Previously Sites.Read.All, Files.Read.All — update in Azure AD
                     app registration to enable write operations.)

In tools_config.json reference secrets as:
  "client_secret": "env:SHAREPOINT_CLIENT_SECRET"

Tools exported:
  SITES
    list_sharepoint_sites           - list all accessible SharePoint sites
    get_sharepoint_site             - get site metadata and storage stats

  DRIVES (Document Libraries)
    list_sharepoint_drives          - list document libraries in a site
    list_sharepoint_drive_items     - list files and folders in a library or subfolder

  FILES (READ)
    search_sharepoint_files         - search files by name or content keyword
    get_sharepoint_file_content     - download and return text content of a file
    get_sharepoint_file_metadata    - get file metadata (size, type, author, dates)

  FILES (WRITE)
    create_sharepoint_folder        - create a new folder in a document library
    upload_sharepoint_file          - upload a text file to a document library
    update_sharepoint_file          - replace content of an existing file
    delete_sharepoint_file          - permanently delete a file or folder
    move_sharepoint_file            - move a file to a different location
    copy_sharepoint_file            - copy a file to a destination folder

  LISTS (READ)
    list_sharepoint_lists           - list SharePoint lists in a site
    get_sharepoint_list_items       - query list items with optional OData filter

  LISTS (WRITE)
    create_sharepoint_list_item     - create a new item in a SharePoint list
    update_sharepoint_list_item     - update fields of an existing list item
    delete_sharepoint_list_item     - delete a list item

  SEARCH
    search_sharepoint               - full-text search across all SharePoint content

  PAGES
    list_sharepoint_pages           - list modern SharePoint pages in a site
    get_sharepoint_page             - get the text content of a SharePoint page
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

from config import get_config

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_MAX_CONTENT_CHARS = 50_000

# Reuse MSAL ConfidentialClientApplication instances across calls.
# Each instance carries an in-memory token cache, so subsequent calls within
# the token TTL (~1 h) skip the roundtrip to Azure AD entirely.
_msal_apps: dict[str, Any] = {}
_msal_lock = threading.Lock()

_TEXT_EXTS = frozenset({
    ".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cs",
    ".cpp", ".c", ".h", ".go", ".rb", ".php", ".sh",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".sql", ".r", ".scala", ".kt", ".swift", ".rs",
})
_TEXT_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/toml",
    "application/csv",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Acquire (or return cached) an Azure AD access token for Graph API."""
    key = f"{tenant_id}:{client_id}"
    with _msal_lock:
        if key not in _msal_apps:
            import msal
            _msal_apps[key] = msal.ConfidentialClientApplication(
                client_id=client_id,
                authority=f"https://login.microsoftonline.com/{tenant_id}",
                client_credential=client_secret,
            )
    app = _msal_apps[key]
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(
            "MSAL token acquisition failed: "
            + (result.get("error_description") or result.get("error") or str(result))
        )
    return result["access_token"]


def _session(token: str):
    """Return a requests.Session pre-loaded with the Graph auth header."""
    import requests
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
    return sess


def _graph_get(sess, path: str, params: dict | None = None) -> dict:
    resp = sess.get(f"{_GRAPH_BASE}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _graph_post(sess, path: str, json_body: dict | None = None) -> dict:
    resp = sess.post(
        f"{_GRAPH_BASE}{path}",
        json=json_body,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _graph_patch(sess, path: str, json_body: dict | None = None) -> dict:
    resp = sess.patch(
        f"{_GRAPH_BASE}{path}",
        json=json_body,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _graph_put_bytes(sess, path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
    resp = sess.put(
        f"{_GRAPH_BASE}{path}",
        data=data,
        headers={"Content-Type": content_type},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _graph_delete(sess, path: str) -> bool:
    resp = sess.delete(f"{_GRAPH_BASE}{path}", timeout=30)
    resp.raise_for_status()
    return True


def _cfg_vals(cfg: dict) -> tuple[str, str, str, str, str]:
    return (
        cfg.get("tenant_id", ""),
        cfg.get("client_id", ""),
        cfg.get("client_secret", ""),
        cfg.get("site_url", ""),
        cfg.get("search_region", "NAM"),  # Required by Graph Search API with app permissions
    )


def _resolve_site_id(sess, site_id_or_url: str, default_site_url: str) -> str:
    """Resolve a site_id, a full site URL, or fall back to default_site_url."""
    target = site_id_or_url or default_site_url
    if not target:
        raise ValueError(
            "No site_id provided and default_site_url is not configured."
        )
    if target.startswith("http"):
        from urllib.parse import urlparse
        parsed = urlparse(target)
        host = parsed.netloc
        path = parsed.path
        data = _graph_get(sess, f"/sites/{host}:{path}")
        return data["id"]
    return target


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def get_tools() -> list[Callable]:

    # ── SITES ─────────────────────────────────────────────────────────────────

    def list_sharepoint_sites(search: str = "", max_results: int = 20) -> dict:
        """List accessible SharePoint sites in the tenant.

        Use this to discover which SharePoint sites exist before drilling into
        document libraries, lists, or pages.

        Args:
            search: Optional keyword to filter sites by display name or URL.
                    Leave blank to return the most recently active sites.
            max_results: Maximum number of sites to return (default 20).

        Returns:
            dict with list of sites (id, name, web_url, description, created_at).
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, _, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            params: dict = {"$top": max_results}
            if search:
                params["search"] = search
            data = _graph_get(sess, "/sites", params=params)
            sites = [
                {
                    "id": s["id"],
                    "name": s.get("displayName", ""),
                    "web_url": s.get("webUrl", ""),
                    "description": s.get("description", ""),
                    "created_at": s.get("createdDateTime", ""),
                }
                for s in data.get("value", [])
            ]
            return {"sites": sites, "count": len(sites)}
        except Exception as exc:
            logger.error("list_sharepoint_sites error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_sharepoint_site(site_id: str = "") -> dict:
        """Get metadata and storage statistics for a SharePoint site.

        Use this after list_sharepoint_sites to inspect a specific site's details.

        Args:
            site_id: SharePoint site ID or full site URL
                     (e.g. 'contoso.sharepoint.com,abc123...,xyz456...' or
                     'https://contoso.sharepoint.com/sites/Engineering').
                     Uses the default site_url from config if not specified.

        Returns:
            dict with id, name, URL, description, created_at, last_modified,
            storage_used_bytes, and storage_total_bytes.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, default_url, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            sid = _resolve_site_id(sess, site_id, default_url)
            data = _graph_get(sess, f"/sites/{sid}")
            quota: dict = {}
            try:
                drv = _graph_get(sess, f"/sites/{sid}/drive")
                quota = drv.get("quota", {})
            except Exception:
                pass
            return {
                "id": data.get("id", ""),
                "name": data.get("displayName", ""),
                "web_url": data.get("webUrl", ""),
                "description": data.get("description", ""),
                "created_at": data.get("createdDateTime", ""),
                "last_modified": data.get("lastModifiedDateTime", ""),
                "storage_used_bytes": quota.get("used", 0),
                "storage_total_bytes": quota.get("total", 0),
            }
        except Exception as exc:
            logger.error("get_sharepoint_site error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DRIVES ────────────────────────────────────────────────────────────────

    def list_sharepoint_drives(site_id: str = "") -> dict:
        """List document libraries (drives) in a SharePoint site.

        Use this to discover which document libraries exist before listing or
        downloading files. Each library has its own drive_id used by file tools.

        Args:
            site_id: SharePoint site ID or URL. Uses default site from config if blank.

        Returns:
            dict with list of drives (id, name, drive_type, web_url,
            last_modified, quota_used_bytes).
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, default_url, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            sid = _resolve_site_id(sess, site_id, default_url)
            data = _graph_get(sess, f"/sites/{sid}/drives")
            drives = [
                {
                    "id": d["id"],
                    "name": d.get("name", ""),
                    "drive_type": d.get("driveType", ""),
                    "web_url": d.get("webUrl", ""),
                    "last_modified": d.get("lastModifiedDateTime", ""),
                    "quota_used_bytes": d.get("quota", {}).get("used", 0),
                }
                for d in data.get("value", [])
            ]
            return {"drives": drives, "count": len(drives), "site_id": sid}
        except Exception as exc:
            logger.error("list_sharepoint_drives error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_sharepoint_drive_items(
        drive_id: str,
        folder_path: str = "",
        max_results: int = 50,
    ) -> dict:
        """List files and folders inside a SharePoint document library or subfolder.

        Use this to browse the contents of a document library. Combine with
        get_sharepoint_file_content to read specific files.

        Args:
            drive_id: Drive ID from list_sharepoint_drives.
            folder_path: Relative path to a subfolder (e.g. 'Engineering/Specs').
                         Leave blank to list the root of the library.
            max_results: Maximum items to return (default 50).

        Returns:
            dict with list of items (id, name, type [file/folder], size_bytes,
            mime_type, created_by, last_modified, web_url, download_url).
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, _, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            if folder_path:
                path = f"/drives/{drive_id}/root:/{folder_path}:/children"
            else:
                path = f"/drives/{drive_id}/root/children"
            data = _graph_get(sess, path, params={"$top": max_results})
            items = [
                {
                    "id": item["id"],
                    "name": item.get("name", ""),
                    "type": "folder" if "folder" in item else "file",
                    "size_bytes": item.get("size", 0),
                    "mime_type": item.get("file", {}).get("mimeType", "") if "file" in item else "",
                    "created_by": item.get("createdBy", {}).get("user", {}).get("displayName", ""),
                    "last_modified": item.get("lastModifiedDateTime", ""),
                    "web_url": item.get("webUrl", ""),
                    "download_url": item.get("@microsoft.graph.downloadUrl", ""),
                }
                for item in data.get("value", [])
            ]
            return {"items": items, "count": len(items), "drive_id": drive_id}
        except Exception as exc:
            logger.error("list_sharepoint_drive_items error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── FILES ─────────────────────────────────────────────────────────────────

    def search_sharepoint_files(
        query: str,
        site_id: str = "",
        max_results: int = 20,
    ) -> dict:
        """Search for files in SharePoint by name or keyword.

        Use this to find documents when you know a keyword in the file name
        or its content. Returns file metadata and resource IDs for further retrieval.

        Args:
            query: Search query — file name, keyword, or phrase
                   (e.g. 'Q3 report', 'architecture diagram', 'onboarding').
            site_id: Restrict search to a specific site ID or URL.
                     Uses default site from config if blank.
            max_results: Maximum files to return (default 20).

        Returns:
            dict with list of matching files (item_id, drive_id, name, size_bytes,
            mime_type, parent_path, web_url, last_modified, last_modified_by, created_by).
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        if not query or not query.strip():
            return {"status": "error", "message": "query must be a non-empty keyword or phrase."}
        try:
            tenant_id, client_id, client_secret, default_url, region = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)

            # Use the Microsoft Search API so we work across all drives in the tenant.
            # Optionally scope to a specific site when site_id is given.
            # Scope to a site using the path: qualifier in the query string.
            # contentSources is for external connectors only — not SharePoint.
            scoped_query = query
            if site_id or default_url:
                site_url = site_id if site_id.startswith("http") else default_url
                if site_url:
                    scoped_query = f"{query} path:\"{site_url}\""

            request_body: dict = {
                "entityTypes": ["driveItem"],
                "query": {"queryString": scoped_query},
                "size": max_results,
                "region": region,
                "fields": [
                    "id", "name", "size", "webUrl", "lastModifiedDateTime",
                    "createdBy", "lastModifiedBy", "parentReference", "file",
                ],
            }

            resp = sess.post(
                f"{_GRAPH_BASE}/search/query",
                json={"requests": [request_body]},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            files = []
            for response_block in data.get("value", []):
                for hit_container in response_block.get("hitsContainers", []):
                    for hit in hit_container.get("hits", []):
                        r = hit.get("resource", {})
                        files.append({
                            "item_id": r.get("id", ""),
                            "name": r.get("name", ""),
                            "size_bytes": r.get("size", 0),
                            "mime_type": r.get("file", {}).get("mimeType", "") if "file" in r else "",
                            "drive_id": r.get("parentReference", {}).get("driveId", ""),
                            "parent_path": r.get("parentReference", {}).get("path", ""),
                            "web_url": r.get("webUrl", ""),
                            "last_modified": r.get("lastModifiedDateTime", ""),
                            "last_modified_by": r.get("lastModifiedBy", {}).get("user", {}).get("displayName", ""),
                            "created_by": r.get("createdBy", {}).get("user", {}).get("displayName", ""),
                            "summary": hit.get("summary", ""),
                        })
            return {"files": files, "count": len(files)}
        except Exception as exc:
            logger.error("search_sharepoint_files error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_sharepoint_file_content(drive_id: str, item_id: str) -> dict:
        """Download and return the text content of a SharePoint file.

        Use this after search_sharepoint_files or list_sharepoint_drive_items
        to read the actual content of a document.

        Supported text types: .txt, .md, .csv, .json, .xml, .html, .py, .js,
        .ts, .java, .cs, .cpp, .go, .yaml, .toml, .ini, .sql, and similar
        plain-text formats. Binary files (PDF, Word, Excel, images) return
        metadata only with an explanatory note.

        Args:
            drive_id: Drive ID containing the file.
            item_id: Item ID of the file (from search or list results).

        Returns:
            dict with name, mime_type, size_bytes, web_url, content (text),
            and truncated flag. Binary/unsupported types return content=None.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            import requests as req

            tenant_id, client_id, client_secret, _, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)

            meta = _graph_get(sess, f"/drives/{drive_id}/items/{item_id}")
            name = meta.get("name", "")
            mime = meta.get("file", {}).get("mimeType", "") if "file" in meta else ""
            size = meta.get("size", 0)
            web_url = meta.get("webUrl", "")

            ext = os.path.splitext(name)[1].lower()
            is_text = ext in _TEXT_EXTS or any(mime.startswith(p) for p in _TEXT_MIME_PREFIXES)

            if not is_text:
                return {
                    "name": name,
                    "item_id": item_id,
                    "drive_id": drive_id,
                    "mime_type": mime,
                    "size_bytes": size,
                    "web_url": web_url,
                    "content": None,
                    "note": f"Binary/unsupported file type ({mime or ext}). Content not extracted.",
                }

            download_url = meta.get("@microsoft.graph.downloadUrl", "")
            if download_url:
                resp = req.get(download_url, timeout=30)
            else:
                resp = sess.get(
                    f"{_GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content",
                    allow_redirects=True,
                    timeout=30,
                )
            resp.raise_for_status()
            text = resp.content.decode("utf-8", errors="replace")
            return {
                "name": name,
                "item_id": item_id,
                "drive_id": drive_id,
                "mime_type": mime,
                "size_bytes": size,
                "web_url": web_url,
                "content": text[:_MAX_CONTENT_CHARS],
                "truncated": len(text) > _MAX_CONTENT_CHARS,
            }
        except Exception as exc:
            logger.error("get_sharepoint_file_content error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_sharepoint_file_metadata(drive_id: str, item_id: str) -> dict:
        """Get detailed metadata for a SharePoint file without downloading it.

        Use this to check file properties — author, size, version count, dates —
        before deciding whether to download the full content.

        Args:
            drive_id: Drive ID containing the file.
            item_id: Item ID of the file.

        Returns:
            dict with name, mime_type, size_bytes, created_at, created_by,
            last_modified, last_modified_by, parent_path, web_url,
            version_count, and etag.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, _, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            item = _graph_get(
                sess,
                f"/drives/{drive_id}/items/{item_id}",
                params={"$expand": "versions($select=id,lastModifiedDateTime,size)"},
            )
            return {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "mime_type": item.get("file", {}).get("mimeType", "") if "file" in item else "",
                "size_bytes": item.get("size", 0),
                "created_at": item.get("createdDateTime", ""),
                "created_by": item.get("createdBy", {}).get("user", {}).get("displayName", ""),
                "last_modified": item.get("lastModifiedDateTime", ""),
                "last_modified_by": item.get("lastModifiedBy", {}).get("user", {}).get("displayName", ""),
                "parent_path": item.get("parentReference", {}).get("path", ""),
                "drive_id": item.get("parentReference", {}).get("driveId", ""),
                "web_url": item.get("webUrl", ""),
                "version_count": len(item.get("versions", [])),
                "etag": item.get("eTag", ""),
            }
        except Exception as exc:
            logger.error("get_sharepoint_file_metadata error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── LISTS ─────────────────────────────────────────────────────────────────

    def list_sharepoint_lists(site_id: str = "") -> dict:
        """List SharePoint Lists in a site.

        SharePoint Lists are structured data tables used for tracking tasks,
        contacts, inventory, issue registers, project logs, and more.
        Hidden system lists are excluded automatically.

        Args:
            site_id: SharePoint site ID or URL. Uses default site from config if blank.

        Returns:
            dict with list of SharePoint lists (id, name, description,
            list_type, last_modified, web_url).
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, default_url, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            sid = _resolve_site_id(sess, site_id, default_url)
            data = _graph_get(
                sess,
                f"/sites/{sid}/lists",
                params={"$select": "id,displayName,description,list,lastModifiedDateTime,webUrl"},
            )
            lists = [
                {
                    "id": lst["id"],
                    "name": lst.get("displayName", ""),
                    "description": lst.get("description", ""),
                    "list_type": lst.get("list", {}).get("template", ""),
                    "last_modified": lst.get("lastModifiedDateTime", ""),
                    "web_url": lst.get("webUrl", ""),
                }
                for lst in data.get("value", [])
                if not lst.get("list", {}).get("hidden", False)
            ]
            return {"lists": lists, "count": len(lists), "site_id": sid}
        except Exception as exc:
            logger.error("list_sharepoint_lists error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_sharepoint_list_items(
        list_id: str,
        site_id: str = "",
        filter_query: str = "",
        select_fields: str = "",
        max_results: int = 50,
    ) -> dict:
        """Get items from a SharePoint List with optional OData filtering.

        Use this to read structured data from SharePoint Lists — task trackers,
        issue registers, contact lists, asset inventories, etc.

        Args:
            list_id: SharePoint List ID from list_sharepoint_lists.
            site_id: Site ID or URL. Uses default site from config if blank.
            filter_query: OData filter expression, e.g.:
                          "fields/Status eq 'Active'"
                          "fields/Priority eq 'High'"
                          "fields/DueDate le '2026-06-01T00:00:00Z'"
            select_fields: Comma-separated field names to include, e.g.
                           'Title,Status,AssignedTo,DueDate'.
                           Returns all fields if blank.
            max_results: Maximum items to return (default 50).

        Returns:
            dict with list of items, each containing id, created_at,
            last_modified, and all requested fields.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, default_url, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            sid = _resolve_site_id(sess, site_id, default_url)
            params: dict = {"$top": max_results, "$expand": "fields"}
            if filter_query:
                params["$filter"] = filter_query
            if select_fields:
                field_select = ",".join(
                    f"fields/{f.strip()}" for f in select_fields.split(",")
                )
                params["$select"] = f"id,createdDateTime,lastModifiedDateTime,{field_select}"
            data = _graph_get(sess, f"/sites/{sid}/lists/{list_id}/items", params=params)
            items = [
                {
                    "id": it["id"],
                    "created_at": it.get("createdDateTime", ""),
                    "last_modified": it.get("lastModifiedDateTime", ""),
                    "fields": {
                        k: v
                        for k, v in it.get("fields", {}).items()
                        if not k.startswith("@") and not k.endswith("_x005f_")
                    },
                }
                for it in data.get("value", [])
            ]
            return {"items": items, "count": len(items), "list_id": list_id, "site_id": sid}
        except Exception as exc:
            logger.error("get_sharepoint_list_items error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── SEARCH ────────────────────────────────────────────────────────────────

    def search_sharepoint(
        query: str,
        content_types: str = "driveItem,listItem,site,list",
        max_results: int = 20,
    ) -> dict:
        """Full-text search across all SharePoint content in the tenant.

        Use this as the primary discovery tool when you don't know which site
        or library contains the information you need. Searches files, list items,
        pages, and sites simultaneously via the Microsoft Search API.

        Args:
            query: Full-text search query (keywords or phrases), e.g.
                   'quarterly budget 2026', 'onboarding checklist', 'API design'.
            content_types: Comma-separated entity types to search.
                           Default: 'driveItem,listItem,site,list'.
                           Valid values: driveItem, listItem, site, list.
            max_results: Maximum results per entity type (default 20).

        Returns:
            dict with results grouped by type — files (driveItem), list_items,
            sites, lists — each with name, web_url, summary, and resource IDs.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, _, region = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)

            entity_types = [t.strip() for t in content_types.split(",") if t.strip()]
            body = {
                "requests": [
                    {
                        "entityTypes": entity_types,
                        "query": {"queryString": query},
                        "size": max_results,
                        "region": region,
                        "fields": [
                            "id", "name", "webUrl", "summary", "title",
                            "lastModifiedDateTime", "createdBy",
                            "siteId", "driveId", "listId",
                        ],
                    }
                ]
            }
            resp = sess.post(f"{_GRAPH_BASE}/search/query", json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            result: dict[str, list] = {
                "files": [], "list_items": [], "sites": [], "lists": [], "other": [],
            }
            for response_block in data.get("value", []):
                for hit_container in response_block.get("hitsContainers", []):
                    for hit in hit_container.get("hits", []):
                        resource = hit.get("resource", {})
                        etype = resource.get("@odata.type", "").lower()
                        entry = {
                            "id": resource.get("id", ""),
                            "name": resource.get("name", "") or resource.get("displayName", ""),
                            "web_url": resource.get("webUrl", ""),
                            "summary": hit.get("summary", ""),
                            "last_modified": resource.get("lastModifiedDateTime", ""),
                        }
                        if "driveitem" in etype:
                            entry["drive_id"] = resource.get("parentReference", {}).get("driveId", "")
                            entry["site_id"] = resource.get("parentReference", {}).get("siteId", "")
                            entry["item_id"] = resource.get("id", "")
                            result["files"].append(entry)
                        elif "listitem" in etype:
                            entry["list_id"] = resource.get("sharepointIds", {}).get("listId", "")
                            entry["site_id"] = resource.get("sharepointIds", {}).get("siteId", "")
                            result["list_items"].append(entry)
                        elif "#microsoft.graph.site" in etype:
                            result["sites"].append(entry)
                        elif "list" in etype:
                            result["lists"].append(entry)
                        else:
                            result["other"].append(entry)

            total = sum(len(v) for v in result.values())
            return {"results": result, "total": total, "query": query}
        except Exception as exc:
            logger.error("search_sharepoint error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── PAGES ─────────────────────────────────────────────────────────────────

    def list_sharepoint_pages(site_id: str = "", max_results: int = 20) -> dict:
        """List modern SharePoint pages in a site.

        Use this to discover wiki-style intranet pages, department homepages,
        news articles, and knowledge-base pages published in SharePoint.

        Args:
            site_id: Site ID or URL. Uses default site from config if blank.
            max_results: Maximum pages to return (default 20).

        Returns:
            dict with list of pages (id, name, title, web_url,
            last_modified, last_modified_by, publishing_state).
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, default_url, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            sid = _resolve_site_id(sess, site_id, default_url)
            data = _graph_get(
                sess,
                f"/sites/{sid}/pages",
                params={
                    "$top": max_results,
                    "$select": (
                        "id,name,title,webUrl,lastModifiedDateTime,"
                        "lastModifiedBy,publishingState"
                    ),
                },
            )
            pages = [
                {
                    "id": pg.get("id", ""),
                    "name": pg.get("name", ""),
                    "title": pg.get("title", ""),
                    "web_url": pg.get("webUrl", ""),
                    "last_modified": pg.get("lastModifiedDateTime", ""),
                    "last_modified_by": pg.get("lastModifiedBy", {}).get("user", {}).get("displayName", ""),
                    "publishing_state": pg.get("publishingState", {}).get("level", ""),
                }
                for pg in data.get("value", [])
            ]
            return {"pages": pages, "count": len(pages), "site_id": sid}
        except Exception as exc:
            logger.error("list_sharepoint_pages error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_sharepoint_page(page_id: str, site_id: str = "") -> dict:
        """Get the text content of a modern SharePoint page.

        Use this after list_sharepoint_pages to read the full content of a
        specific intranet page or wiki article. HTML markup is stripped;
        only plain text is returned.

        Args:
            page_id: Page ID from list_sharepoint_pages.
            site_id: Site ID or URL. Uses default site from config if blank.

        Returns:
            dict with id, title, web_url, site_id, content (plain text),
            and truncated flag.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            from bs4 import BeautifulSoup

            tenant_id, client_id, client_secret, default_url, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            sid = _resolve_site_id(sess, site_id, default_url)
            page = _graph_get(
                sess,
                f"/sites/{sid}/pages/{page_id}/microsoft.graph.sitePage",
                params={"$expand": "canvasLayout"},
            )
            title = page.get("title", "")
            web_url = page.get("webUrl", "")

            chunks: list[str] = []
            for section in page.get("canvasLayout", {}).get("horizontalSections", []):
                for col in section.get("columns", []):
                    for webpart in col.get("webparts", []):
                        inner = (
                            webpart.get("innerHtml", "")
                            or webpart.get("data", {}).get("innerHTML", "")
                        )
                        if inner:
                            text = BeautifulSoup(inner, "html.parser").get_text(
                                separator="\n", strip=True
                            )
                            if text:
                                chunks.append(text)

            content = "\n\n".join(chunks)
            return {
                "id": page_id,
                "title": title,
                "web_url": web_url,
                "site_id": sid,
                "content": content[:_MAX_CONTENT_CHARS],
                "truncated": len(content) > _MAX_CONTENT_CHARS,
            }
        except Exception as exc:
            logger.error("get_sharepoint_page error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── FILES (WRITE) ─────────────────────────────────────────────────────────

    def create_sharepoint_folder(
        drive_id: str,
        folder_name: str,
        parent_folder_path: str = "",
    ) -> dict:
        """Create a new folder in a SharePoint document library.

        Args:
            drive_id: Drive ID from list_sharepoint_drives.
            folder_name: Name for the new folder.
            parent_folder_path: Relative path inside the drive for the parent
                                folder (e.g. 'Engineering/Specs').
                                Leave blank to create in the drive root.

        Returns:
            dict with folder id, name, web_url, and status.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, _, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)

            if parent_folder_path:
                path = f"/drives/{drive_id}/root:/{parent_folder_path}:/children"
            else:
                path = f"/drives/{drive_id}/root/children"

            body = {
                "name": folder_name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename",
            }
            result = _graph_post(sess, path, json_body=body)
            return {
                "id": result.get("id", ""),
                "name": result.get("name", folder_name),
                "web_url": result.get("webUrl", ""),
                "drive_id": drive_id,
                "status": "created",
            }
        except Exception as exc:
            logger.error("create_sharepoint_folder error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def upload_sharepoint_file(
        drive_id: str,
        file_name: str,
        content: str,
        folder_path: str = "",
    ) -> dict:
        """Upload a new text file to a SharePoint document library.

        Args:
            drive_id: Drive ID from list_sharepoint_drives.
            file_name: File name including extension (e.g. 'report.md', 'data.csv').
            content: File content as a UTF-8 string.
            folder_path: Destination folder path inside the drive
                         (e.g. 'Engineering/Reports'). Leave blank for drive root.

        Returns:
            dict with file id, name, drive_id, web_url, and status.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, _, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)

            if folder_path:
                path = f"/drives/{drive_id}/root:/{folder_path}/{file_name}:/content"
            else:
                path = f"/drives/{drive_id}/root:/{file_name}:/content"

            result = _graph_put_bytes(sess, path, data=content.encode("utf-8"), content_type="text/plain")
            return {
                "id": result.get("id", ""),
                "name": result.get("name", file_name),
                "drive_id": drive_id,
                "web_url": result.get("webUrl", ""),
                "status": "uploaded",
            }
        except Exception as exc:
            logger.error("upload_sharepoint_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_sharepoint_file(drive_id: str, item_id: str, content: str) -> dict:
        """Replace the content of an existing SharePoint file.

        Args:
            drive_id: Drive ID containing the file.
            item_id: Item ID of the file to update.
            content: New file content as a UTF-8 string.

        Returns:
            dict with file id, name, web_url, and status.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, _, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)

            result = _graph_put_bytes(
                sess,
                f"/drives/{drive_id}/items/{item_id}/content",
                data=content.encode("utf-8"),
                content_type="text/plain",
            )
            return {
                "id": result.get("id", item_id),
                "name": result.get("name", ""),
                "web_url": result.get("webUrl", ""),
                "status": "updated",
            }
        except Exception as exc:
            logger.error("update_sharepoint_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_sharepoint_file(drive_id: str, item_id: str) -> dict:
        """Permanently delete a file or folder from a SharePoint document library.

        Args:
            drive_id: Drive ID containing the item.
            item_id: Item ID of the file or folder to delete.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, _, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            _graph_delete(sess, f"/drives/{drive_id}/items/{item_id}")
            return {"item_id": item_id, "drive_id": drive_id, "status": "deleted"}
        except Exception as exc:
            logger.error("delete_sharepoint_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def move_sharepoint_file(
        drive_id: str,
        item_id: str,
        destination_drive_id: str,
        destination_folder_path: str,
    ) -> dict:
        """Move a file to a different location within SharePoint.

        Args:
            drive_id: Drive ID of the source file.
            item_id: Item ID of the file to move.
            destination_drive_id: Drive ID of the destination (can be same drive).
            destination_folder_path: Folder path in the destination drive
                                     (e.g. 'Archive/2026'). Use '' for root.

        Returns:
            dict with updated item id, name, web_url, and status.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, _, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)

            if destination_folder_path:
                dest_meta = _graph_get(
                    sess,
                    f"/drives/{destination_drive_id}/root:/{destination_folder_path}",
                )
            else:
                dest_meta = _graph_get(sess, f"/drives/{destination_drive_id}/root")
            dest_id = dest_meta.get("id", "")

            result = _graph_patch(
                sess,
                f"/drives/{drive_id}/items/{item_id}",
                json_body={"parentReference": {"driveId": destination_drive_id, "id": dest_id}},
            )
            return {
                "id": result.get("id", item_id),
                "name": result.get("name", ""),
                "web_url": result.get("webUrl", ""),
                "status": "moved",
            }
        except Exception as exc:
            logger.error("move_sharepoint_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def copy_sharepoint_file(
        drive_id: str,
        item_id: str,
        destination_drive_id: str,
        destination_folder_path: str,
        new_name: str = "",
    ) -> dict:
        """Copy a SharePoint file to a destination folder.

        Graph API copies are asynchronous — this tool initiates the copy
        and returns a monitor URL. The copy completes within seconds.

        Args:
            drive_id: Drive ID of the source file.
            item_id: Item ID of the file to copy.
            destination_drive_id: Drive ID of the destination.
            destination_folder_path: Folder path in the destination drive. Use '' for root.
            new_name: New name for the copy. Keeps original name if blank.

        Returns:
            dict with status and monitor_url to check completion.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, _, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)

            if destination_folder_path:
                dest_meta = _graph_get(
                    sess,
                    f"/drives/{destination_drive_id}/root:/{destination_folder_path}",
                )
            else:
                dest_meta = _graph_get(sess, f"/drives/{destination_drive_id}/root")
            dest_id = dest_meta.get("id", "")

            body: dict = {"parentReference": {"driveId": destination_drive_id, "id": dest_id}}
            if new_name:
                body["name"] = new_name

            resp = sess.post(
                f"{_GRAPH_BASE}/drives/{drive_id}/items/{item_id}/copy",
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            monitor_url = resp.headers.get("Location", "")
            return {
                "item_id": item_id,
                "destination_folder": destination_folder_path,
                "monitor_url": monitor_url,
                "status": "copy_initiated",
            }
        except Exception as exc:
            logger.error("copy_sharepoint_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── LISTS (WRITE) ─────────────────────────────────────────────────────────

    def create_sharepoint_list_item(
        list_id: str,
        fields: dict,
        site_id: str = "",
    ) -> dict:
        """Create a new item in a SharePoint List.

        Args:
            list_id: SharePoint List ID from list_sharepoint_lists.
            fields: Dictionary of field name → value pairs for the new item.
                    Example: {"Title": "New task", "Status": "Active", "Priority": "High"}
                    Field names must match the internal names of the list's columns.
            site_id: Site ID or URL. Uses default site from config if blank.

        Returns:
            dict with new item id, fields, and status.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, default_url, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            sid = _resolve_site_id(sess, site_id, default_url)

            result = _graph_post(
                sess,
                f"/sites/{sid}/lists/{list_id}/items",
                json_body={"fields": fields},
            )
            return {
                "id": result.get("id", ""),
                "fields": result.get("fields", fields),
                "list_id": list_id,
                "site_id": sid,
                "status": "created",
            }
        except Exception as exc:
            logger.error("create_sharepoint_list_item error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_sharepoint_list_item(
        list_id: str,
        item_id: str,
        fields: dict,
        site_id: str = "",
    ) -> dict:
        """Update fields of an existing SharePoint List item.

        Only the fields you provide are changed; omitted fields stay as-is.

        Args:
            list_id: SharePoint List ID.
            item_id: List item ID to update (from get_sharepoint_list_items).
            fields: Dictionary of field name → new value pairs.
                    Example: {"Status": "Completed", "AssignedTo": "alice@company.com"}
            site_id: Site ID or URL. Uses default site from config if blank.

        Returns:
            dict with updated item id and status.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, default_url, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            sid = _resolve_site_id(sess, site_id, default_url)

            _graph_patch(
                sess,
                f"/sites/{sid}/lists/{list_id}/items/{item_id}/fields",
                json_body=fields,
            )
            return {
                "id": item_id,
                "list_id": list_id,
                "site_id": sid,
                "updated_fields": list(fields.keys()),
                "status": "updated",
            }
        except Exception as exc:
            logger.error("update_sharepoint_list_item error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_sharepoint_list_item(
        list_id: str,
        item_id: str,
        site_id: str = "",
    ) -> dict:
        """Delete an item from a SharePoint List.

        Args:
            list_id: SharePoint List ID.
            item_id: List item ID to delete.
            site_id: Site ID or URL. Uses default site from config if blank.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("sharepoint")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "SharePoint tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, default_url, _ = _cfg_vals(cfg.config)
            token = _get_token(tenant_id, client_id, client_secret)
            sess = _session(token)
            sid = _resolve_site_id(sess, site_id, default_url)

            _graph_delete(sess, f"/sites/{sid}/lists/{list_id}/items/{item_id}")
            return {
                "id": item_id,
                "list_id": list_id,
                "site_id": sid,
                "status": "deleted",
            }
        except Exception as exc:
            logger.error("delete_sharepoint_list_item error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Sites
        list_sharepoint_sites,
        get_sharepoint_site,
        # Drives (Document Libraries)
        list_sharepoint_drives,
        list_sharepoint_drive_items,
        # Files (Read)
        search_sharepoint_files,
        get_sharepoint_file_content,
        get_sharepoint_file_metadata,
        # Files (Write)
        create_sharepoint_folder,
        upload_sharepoint_file,
        update_sharepoint_file,
        delete_sharepoint_file,
        move_sharepoint_file,
        copy_sharepoint_file,
        # Lists (Read)
        list_sharepoint_lists,
        get_sharepoint_list_items,
        # Lists (Write)
        create_sharepoint_list_item,
        update_sharepoint_list_item,
        delete_sharepoint_list_item,
        # Search
        search_sharepoint,
        # Pages
        list_sharepoint_pages,
        get_sharepoint_page,
    ]
