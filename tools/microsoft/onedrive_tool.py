"""OneDrive tool — Microsoft Graph API v1.0 integration.

Required credentials (set in tools_config.json or env vars):
  tenant_id     : Azure AD tenant ID
  client_id     : App registration client ID
  client_secret : App registration client secret (use env:ONEDRIVE_CLIENT_SECRET)
  user_email    : The mailbox/UPN of the user whose OneDrive to access
                  (e.g. riya@stratova.ai)

Azure AD app registration requirements:
  Permission type : Application (not Delegated)
  Permissions     : Files.Read.All

In tools_config.json, reference secrets as:
  "client_secret": "env:ONEDRIVE_CLIENT_SECRET"

Tools exported:
  search_onedrive          - search files by name or keyword across OneDrive
  list_onedrive_files      - list files and folders in a folder path
  get_onedrive_file_content - download and return text content of a file
"""
from __future__ import annotations

import logging
import os
from typing import Callable

from config import get_config
from tools.microsoft.graph_utils import get_token, graph_session, graph_get

logger = logging.getLogger(__name__)

_MAX_CONTENT_CHARS = 50_000

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


def _cfg_vals(cfg: dict) -> tuple[str, str, str, str]:
    return (
        cfg.get("tenant_id", ""),
        cfg.get("client_id", ""),
        cfg.get("client_secret", ""),
        cfg.get("user_email", ""),
    )


def get_tools() -> list[Callable]:

    def search_onedrive(query: str, max_results: int = 20) -> dict:
        """Search for files in a user's OneDrive by name or keyword.

        Use this to find documents, spreadsheets, presentations, and other files
        stored in OneDrive. Returns file metadata and IDs for further retrieval.

        Args:
            query: Search keywords or phrase — file name, content keyword, or phrase
                   (e.g. 'Q3 budget', 'product roadmap', 'onboarding').
            max_results: Maximum files to return (default 20).

        Returns:
            dict with list of matching files (id, name, size_bytes, mime_type,
            parent_path, web_url, last_modified, created_by).
        """
        cfg = get_config().tools.get("onedrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "OneDrive tool is currently disabled."}
        if not query or not query.strip():
            return {"status": "error", "message": "query must be a non-empty string."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)
            data = graph_get(
                sess,
                f"/users/{user_email}/drive/search(q='{query}')",
                params={"$top": max_results, "$select": (
                    "id,name,size,webUrl,lastModifiedDateTime,"
                    "createdBy,parentReference,file"
                )},
            )
            files = [
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "size_bytes": item.get("size", 0),
                    "mime_type": item.get("file", {}).get("mimeType", "") if "file" in item else "",
                    "parent_path": item.get("parentReference", {}).get("path", ""),
                    "web_url": item.get("webUrl", ""),
                    "last_modified": item.get("lastModifiedDateTime", ""),
                    "created_by": item.get("createdBy", {}).get("user", {}).get("displayName", ""),
                    "is_folder": "folder" in item,
                }
                for item in data.get("value", [])
            ]
            return {"files": files, "count": len(files)}
        except Exception as exc:
            logger.error("search_onedrive error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_onedrive_files(folder_path: str = "", max_results: int = 50) -> dict:
        """List files and folders inside a OneDrive folder.

        Use this to browse the contents of a user's OneDrive. Start with an empty
        folder_path for the root, then drill into subdirectories.

        Args:
            folder_path: Relative path to a folder (e.g. 'Documents/Projects').
                         Leave blank to list the root of OneDrive.
            max_results: Maximum items to return (default 50).

        Returns:
            dict with list of items (id, name, type [file/folder], size_bytes,
            mime_type, web_url, last_modified, created_by).
        """
        cfg = get_config().tools.get("onedrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "OneDrive tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)
            if folder_path:
                path = f"/users/{user_email}/drive/root:/{folder_path}:/children"
            else:
                path = f"/users/{user_email}/drive/root/children"
            data = graph_get(sess, path, params={"$top": max_results})
            items = [
                {
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "type": "folder" if "folder" in item else "file",
                    "size_bytes": item.get("size", 0),
                    "mime_type": item.get("file", {}).get("mimeType", "") if "file" in item else "",
                    "web_url": item.get("webUrl", ""),
                    "last_modified": item.get("lastModifiedDateTime", ""),
                    "created_by": item.get("createdBy", {}).get("user", {}).get("displayName", ""),
                }
                for item in data.get("value", [])
            ]
            return {"items": items, "count": len(items), "folder_path": folder_path or "/"}
        except Exception as exc:
            logger.error("list_onedrive_files error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_onedrive_file_content(file_id: str) -> dict:
        """Download and return the text content of a OneDrive file.

        Use this after search_onedrive or list_onedrive_files to read the actual
        content of a document. Only plain-text formats are supported; binary files
        (PDF, Word, Excel, images) return metadata only.

        Supported text types: .txt, .md, .csv, .json, .xml, .html, .py, .js,
        .ts, .yaml, .toml, .sql, and similar plain-text formats.

        Args:
            file_id: File ID from search_onedrive or list_onedrive_files results.

        Returns:
            dict with name, mime_type, size_bytes, web_url, content (text),
            and truncated flag. Binary files return content=None with a note.
        """
        cfg = get_config().tools.get("onedrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "OneDrive tool is currently disabled."}
        try:
            import requests as req

            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)

            meta = graph_get(sess, f"/users/{user_email}/drive/items/{file_id}")
            name = meta.get("name", "")
            mime = meta.get("file", {}).get("mimeType", "") if "file" in meta else ""
            size = meta.get("size", 0)
            web_url = meta.get("webUrl", "")

            ext = os.path.splitext(name)[1].lower()
            is_text = ext in _TEXT_EXTS or any(mime.startswith(p) for p in _TEXT_MIME_PREFIXES)

            if not is_text:
                return {
                    "name": name,
                    "file_id": file_id,
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
                    f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{file_id}/content",
                    allow_redirects=True,
                    timeout=30,
                )
            resp.raise_for_status()
            text = resp.content.decode("utf-8", errors="replace")
            return {
                "name": name,
                "file_id": file_id,
                "mime_type": mime,
                "size_bytes": size,
                "web_url": web_url,
                "content": text[:_MAX_CONTENT_CHARS],
                "truncated": len(text) > _MAX_CONTENT_CHARS,
            }
        except Exception as exc:
            logger.error("get_onedrive_file_content error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [search_onedrive, list_onedrive_files, get_onedrive_file_content]
