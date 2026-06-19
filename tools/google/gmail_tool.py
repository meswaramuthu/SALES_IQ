"""Gmail tool — service account with domain-wide delegation.

Setup (one-time, done by Google Workspace admin):
  1. Create a GCP service account and download the JSON key.
  2. Upload the key to GCS (set service_account_key_gcs_uri in tools_config.json).
  3. In Google Workspace Admin → Security → API controls → Domain-wide delegation,
     add the service account client ID with scope:
       https://www.googleapis.com/auth/gmail.readonly
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _build_service(cfg: dict):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    from tools.utils.gcs_utils import read_gcs_bytes

    key_info = json.loads(read_gcs_bytes(cfg["service_account_key_gcs_uri"]))
    creds = service_account.Credentials.from_service_account_info(
        key_info,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    ).with_subject(cfg.get("user_email", ""))
    return build("gmail", "v1", credentials=creds)


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace") if data else ""
    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text
    return ""


def get_tools() -> list[Callable]:
    def search_gmail(query: str, max_results: int = 10) -> dict:
        """Search Gmail messages and email threads.

        Use this tool to find emails by subject, sender, content, date, or label.
        Supports the full Gmail search syntax (e.g. 'from:boss@company.com subject:budget after:2024/01/01').

        Args:
            query: Gmail search query string.
            max_results: Maximum number of messages to return (default 10, max 50).

        Returns:
            dict with a list of email summaries (id, subject, from, date, snippet).
        """
        cfg = get_config().tools.get("gmail")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Gmail tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            limit = min(max_results, cfg.config.get("max_results", 20))
            result = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=limit)
                .execute()
            )
            summaries = []
            for msg in result.get("messages", []):
                meta = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From", "Date"],
                    )
                    .execute()
                )
                hdrs = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
                summaries.append(
                    {
                        "id": msg["id"],
                        "subject": hdrs.get("Subject", "(no subject)"),
                        "from": hdrs.get("From", ""),
                        "date": hdrs.get("Date", ""),
                        "snippet": meta.get("snippet", ""),
                    }
                )
            return {"messages": summaries, "count": len(summaries)}
        except Exception as exc:
            logger.error("Gmail search error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_gmail_message(message_id: str) -> dict:
        """Get the full text content of a Gmail message by its ID.

        Use this after search_gmail to read the complete body of a specific email.

        Args:
            message_id: The Gmail message ID returned by search_gmail.

        Returns:
            dict with subject, from, to, date, and full body text.
        """
        cfg = get_config().tools.get("gmail")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Gmail tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            hdrs = {
                h["name"]: h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            return {
                "id": message_id,
                "subject": hdrs.get("Subject", ""),
                "from": hdrs.get("From", ""),
                "to": hdrs.get("To", ""),
                "date": hdrs.get("Date", ""),
                "body": _extract_body(msg.get("payload", {})),
            }
        except Exception as exc:
            logger.error("Gmail get_message error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [search_gmail, get_gmail_message]
