"""Google Drive tool — service account with domain-wide delegation.

Setup (one-time, done by Google Workspace admin):
  1. Create a GCP service account and download the JSON key.
  2. Upload the key to GCS (set service_account_key_gcs_uri in tools_config.json).
  3. In Google Workspace Admin → Security → API controls → Domain-wide delegation,
     add the service account client ID with scope:
       https://www.googleapis.com/auth/drive.readonly
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)

# Google Workspace MIME types → export format
_EXPORT_MAP: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_MAX_CONTENT_CHARS = 50_000


def _build_service(cfg: dict):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    from tools.utils.gcs_utils import read_gcs_bytes

    key_info = json.loads(read_gcs_bytes(cfg["service_account_key_gcs_uri"]))
    creds = service_account.Credentials.from_service_account_info(
        key_info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    ).with_subject(cfg.get("user_email", ""))
    return build("drive", "v3", credentials=creds)


def get_tools() -> list[Callable]:
    def search_gdrive(query: str, max_results: int = 10) -> dict:
        """Search Google Drive for files and documents.

        Use this tool to find Docs, Sheets, Slides, PDFs, and other files
        stored in Google Drive using full-text search.

        Args:
            query: Search query — keywords, filename fragments, or phrases.
            max_results: Maximum number of files to return (default 10).

        Returns:
            dict with a list of matching files (id, name, type, modified date, URL).
        """
        cfg = get_config().tools.get("gdrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Drive tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            escaped = query.replace("'", "\\'")
            q = f"fullText contains '{escaped}' and trashed = false"
            result = (
                service.files()
                .list(
                    q=q,
                    pageSize=max_results,
                    fields="files(id,name,mimeType,modifiedTime,webViewLink,parents)",
                )
                .execute()
            )
            files = [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "type": f.get("mimeType", ""),
                    "modified": f.get("modifiedTime", ""),
                    "url": f.get("webViewLink", ""),
                }
                for f in result.get("files", [])
            ]
            return {"files": files, "count": len(files)}
        except Exception as exc:
            logger.error("Drive search error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_gdrive_file_content(file_id: str) -> dict:
        """Get the text content of a Google Drive file.

        Use this after search_gdrive to read a specific file's content.
        Supports Google Docs, Sheets, Slides, and plain text files.
        Content is capped at 50 000 characters.

        Args:
            file_id: The Drive file ID returned by search_gdrive.

        Returns:
            dict with file name, type, and text content.
        """
        cfg = get_config().tools.get("gdrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Drive tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
            mime = meta.get("mimeType", "")
            name = meta.get("name", file_id)

            if mime in _EXPORT_MAP:
                raw = service.files().export(fileId=file_id, mimeType=_EXPORT_MAP[mime]).execute()
            else:
                raw = service.files().get_media(fileId=file_id).execute()

            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            return {"name": name, "type": mime, "content": text[:_MAX_CONTENT_CHARS]}
        except Exception as exc:
            logger.error("Drive get_content error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [search_gdrive, get_gdrive_file_content]
