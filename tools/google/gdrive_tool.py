"""Google Drive tool — service account with domain-wide delegation.

Setup (one-time, done by Google Workspace admin):
  1. Create a GCP service account and download the JSON key.
  2. Upload the key to GCS (set service_account_key_gcs_uri in tools_config.json).
  3. In Google Workspace Admin → Security → API controls → Domain-wide delegation,
     add the service account client ID with scope:
       https://www.googleapis.com/auth/drive
     (Previously drive.readonly — update the scope in Admin Console to enable writes.)

Tools exported:
  READ
    search_gdrive            - full-text search for files and documents
    get_gdrive_file_content  - read text content of a file

  CREATE
    create_gdrive_folder     - create a new folder
    upload_gdrive_file       - create a new file with text content
    copy_gdrive_file         - copy an existing file

  UPDATE
    update_gdrive_file       - replace content and/or rename a file
    move_gdrive_file         - move a file to a different folder
    rename_gdrive_file       - rename a file in place

  DELETE
    delete_gdrive_file       - move file to trash (recoverable)
    permanently_delete_gdrive_file - permanently delete a file (irreversible)
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
        scopes=["https://www.googleapis.com/auth/drive"],
    ).with_subject(cfg.get("user_email", ""))
    return build("drive", "v3", credentials=creds)


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

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
            return {"id": file_id, "name": name, "type": mime, "content": text[:_MAX_CONTENT_CHARS]}
        except Exception as exc:
            logger.error("Drive get_content error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_gdrive_folder(name: str, parent_folder_id: str = "") -> dict:
        """Create a new folder in Google Drive.

        Args:
            name: Folder name.
            parent_folder_id: ID of the parent folder. Leave blank to create
                              in the user's root Drive.

        Returns:
            dict with folder id, name, and URL.
        """
        cfg = get_config().tools.get("gdrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Drive tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            metadata: dict = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            if parent_folder_id:
                metadata["parents"] = [parent_folder_id]

            folder = service.files().create(
                body=metadata,
                fields="id,name,webViewLink",
            ).execute()
            return {
                "id": folder.get("id", ""),
                "name": folder.get("name", name),
                "url": folder.get("webViewLink", ""),
                "status": "created",
            }
        except Exception as exc:
            logger.error("Drive create_folder error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def upload_gdrive_file(
        name: str,
        content: str,
        mime_type: str = "text/plain",
        parent_folder_id: str = "",
    ) -> dict:
        """Create a new file in Google Drive with the given text content.

        Use this to upload documents, notes, CSV data, code files, or any
        text-based content. For binary files, use the Drive web UI instead.

        Args:
            name: File name including extension (e.g. 'report.txt', 'data.csv').
            content: Full file content as a UTF-8 string.
            mime_type: MIME type of the file (default 'text/plain').
                       Common values: 'text/plain', 'text/csv', 'text/html',
                       'application/json', 'text/markdown'.
            parent_folder_id: ID of the destination folder. Leave blank to
                               upload to the user's root Drive.

        Returns:
            dict with file id, name, and URL.
        """
        cfg = get_config().tools.get("gdrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Drive tool is currently disabled."}
        try:
            from googleapiclient.http import MediaInMemoryUpload

            service = _build_service(cfg.config)
            metadata: dict = {"name": name}
            if parent_folder_id:
                metadata["parents"] = [parent_folder_id]

            media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type)
            file_obj = service.files().create(
                body=metadata,
                media_body=media,
                fields="id,name,webViewLink",
            ).execute()
            return {
                "id": file_obj.get("id", ""),
                "name": file_obj.get("name", name),
                "url": file_obj.get("webViewLink", ""),
                "status": "uploaded",
            }
        except Exception as exc:
            logger.error("Drive upload_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def copy_gdrive_file(file_id: str, new_name: str = "", parent_folder_id: str = "") -> dict:
        """Copy an existing Google Drive file.

        Args:
            file_id: ID of the file to copy.
            new_name: Name for the copy. Defaults to 'Copy of <original name>'.
            parent_folder_id: Folder to place the copy in. Defaults to the
                               same folder as the original.

        Returns:
            dict with new file id, name, and URL.
        """
        cfg = get_config().tools.get("gdrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Drive tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            body: dict = {}
            if new_name:
                body["name"] = new_name
            if parent_folder_id:
                body["parents"] = [parent_folder_id]

            copy = service.files().copy(
                fileId=file_id,
                body=body,
                fields="id,name,webViewLink",
            ).execute()
            return {
                "id": copy.get("id", ""),
                "name": copy.get("name", ""),
                "url": copy.get("webViewLink", ""),
                "status": "copied",
            }
        except Exception as exc:
            logger.error("Drive copy_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_gdrive_file(file_id: str, content: str = "", new_name: str = "") -> dict:
        """Update the content and/or name of a Google Drive file.

        Provide at least one of content or new_name.

        Args:
            file_id: ID of the file to update.
            content: New file content as a UTF-8 string. Leave blank to
                     keep the existing content unchanged.
            new_name: New file name. Leave blank to keep the existing name.

        Returns:
            dict with file id, name, and URL confirming the update.
        """
        cfg = get_config().tools.get("gdrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Drive tool is currently disabled."}
        if not content and not new_name:
            return {"status": "error", "message": "Provide content or new_name to update."}
        try:
            from googleapiclient.http import MediaInMemoryUpload

            service = _build_service(cfg.config)
            body: dict = {}
            if new_name:
                body["name"] = new_name

            if content:
                meta = service.files().get(fileId=file_id, fields="mimeType").execute()
                mime = meta.get("mimeType", "text/plain")
                media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime)
                result = service.files().update(
                    fileId=file_id,
                    body=body,
                    media_body=media,
                    fields="id,name,webViewLink",
                ).execute()
            else:
                result = service.files().update(
                    fileId=file_id,
                    body=body,
                    fields="id,name,webViewLink",
                ).execute()

            return {
                "id": result.get("id", file_id),
                "name": result.get("name", ""),
                "url": result.get("webViewLink", ""),
                "status": "updated",
            }
        except Exception as exc:
            logger.error("Drive update_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def move_gdrive_file(file_id: str, new_parent_folder_id: str) -> dict:
        """Move a Google Drive file to a different folder.

        Args:
            file_id: ID of the file to move.
            new_parent_folder_id: ID of the destination folder.

        Returns:
            dict with file id, name, and new parent confirming the move.
        """
        cfg = get_config().tools.get("gdrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Drive tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            meta = service.files().get(fileId=file_id, fields="parents,name").execute()
            old_parents = ",".join(meta.get("parents", []))

            result = service.files().update(
                fileId=file_id,
                addParents=new_parent_folder_id,
                removeParents=old_parents,
                fields="id,name,parents,webViewLink",
            ).execute()
            return {
                "id": result.get("id", file_id),
                "name": result.get("name", ""),
                "new_parent": new_parent_folder_id,
                "url": result.get("webViewLink", ""),
                "status": "moved",
            }
        except Exception as exc:
            logger.error("Drive move_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def rename_gdrive_file(file_id: str, new_name: str) -> dict:
        """Rename a Google Drive file.

        Args:
            file_id: ID of the file to rename.
            new_name: New file name (including extension if applicable).

        Returns:
            dict with file id, old name (if available), new name, and URL.
        """
        cfg = get_config().tools.get("gdrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Drive tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            result = service.files().update(
                fileId=file_id,
                body={"name": new_name},
                fields="id,name,webViewLink",
            ).execute()
            return {
                "id": result.get("id", file_id),
                "name": result.get("name", new_name),
                "url": result.get("webViewLink", ""),
                "status": "renamed",
            }
        except Exception as exc:
            logger.error("Drive rename_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_gdrive_file(file_id: str) -> dict:
        """Move a Google Drive file to trash (recoverable from Drive trash).

        The file is not permanently deleted and can be restored within 30 days.
        Use permanently_delete_gdrive_file for immediate permanent removal.

        Args:
            file_id: ID of the file to trash.

        Returns:
            dict confirming the file was moved to trash.
        """
        cfg = get_config().tools.get("gdrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Drive tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            service.files().update(fileId=file_id, body={"trashed": True}).execute()
            return {"id": file_id, "status": "trashed"}
        except Exception as exc:
            logger.error("Drive trash_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def permanently_delete_gdrive_file(file_id: str) -> dict:
        """Permanently delete a Google Drive file. This action is irreversible.

        The file is immediately and permanently removed — it cannot be
        recovered from trash. Use delete_gdrive_file for reversible deletion.

        Args:
            file_id: ID of the file to permanently delete.

        Returns:
            dict confirming permanent deletion.
        """
        cfg = get_config().tools.get("gdrive")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Drive tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            service.files().delete(fileId=file_id).execute()
            return {"id": file_id, "status": "permanently_deleted"}
        except Exception as exc:
            logger.error("Drive delete_file error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        search_gdrive,
        get_gdrive_file_content,
        # Create
        create_gdrive_folder,
        upload_gdrive_file,
        copy_gdrive_file,
        # Update
        update_gdrive_file,
        move_gdrive_file,
        rename_gdrive_file,
        # Delete
        delete_gdrive_file,
        permanently_delete_gdrive_file,
    ]
