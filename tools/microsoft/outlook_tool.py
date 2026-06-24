"""Outlook tool — Microsoft Graph API v1.0 integration (Mail).

Required credentials (set in tools_config.json or env vars):
  tenant_id     : Azure AD tenant ID
  client_id     : App registration client ID
  client_secret : App registration client secret (use env:OUTLOOK_CLIENT_SECRET)
  user_email    : The mailbox/UPN of the user whose mail to access
                  (e.g. riya@stratova.ai)

Azure AD app registration requirements:
  Permission type : Application (not Delegated)
  Permissions     : Mail.Read

In tools_config.json, reference secrets as:
  "client_secret": "env:OUTLOOK_CLIENT_SECRET"

Tools exported:
  search_outlook_emails  - search emails by keyword, sender, or subject
  list_outlook_emails    - list recent emails from a folder (Inbox, Sent, etc.)
  get_outlook_email      - get full content of a specific email
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config
from tools.microsoft.graph_utils import get_token, graph_session, graph_get

logger = logging.getLogger(__name__)

_MAX_BODY_CHARS = 20_000


def _cfg_vals(cfg: dict) -> tuple[str, str, str, str]:
    return (
        cfg.get("tenant_id", ""),
        cfg.get("client_id", ""),
        cfg.get("client_secret", ""),
        cfg.get("user_email", ""),
    )


def _format_message(msg: dict) -> dict:
    body_content = msg.get("body", {}).get("content", "")
    body_type = msg.get("body", {}).get("contentType", "text")
    if body_type == "html":
        try:
            from bs4 import BeautifulSoup
            body_content = BeautifulSoup(body_content, "html.parser").get_text(
                separator="\n", strip=True
            )
        except Exception:
            pass

    return {
        "id": msg.get("id", ""),
        "subject": msg.get("subject", ""),
        "from": (msg.get("from", {}).get("emailAddress", {}) or {}).get("address", ""),
        "from_name": (msg.get("from", {}).get("emailAddress", {}) or {}).get("name", ""),
        "to": [
            r.get("emailAddress", {}).get("address", "")
            for r in msg.get("toRecipients", [])
        ],
        "cc": [
            r.get("emailAddress", {}).get("address", "")
            for r in msg.get("ccRecipients", [])
        ],
        "received_at": msg.get("receivedDateTime", ""),
        "is_read": msg.get("isRead", False),
        "has_attachments": msg.get("hasAttachments", False),
        "importance": msg.get("importance", "normal"),
        "web_link": msg.get("webLink", ""),
        "body_preview": msg.get("bodyPreview", ""),
        "body": body_content[:_MAX_BODY_CHARS] if body_content else "",
        "body_truncated": len(body_content) > _MAX_BODY_CHARS,
    }


def get_tools() -> list[Callable]:

    def search_outlook_emails(
        query: str,
        max_results: int = 10,
    ) -> dict:
        """Search emails in Outlook by keyword, subject, sender, or content.

        Use this to find specific emails — meeting requests, notifications,
        thread discussions, or any email containing a keyword or phrase.

        Args:
            query: Search query. Supports KQL (Keyword Query Language):
                   - Keyword search:   'budget review'
                   - Subject filter:   'subject:Q3 report'
                   - Sender filter:    'from:alice@company.com'
                   - Recipient filter: 'to:bob@company.com'
                   - Date filter:      'received>=2026-01-01'
                   - Combined:         'from:alice subject:roadmap'
            max_results: Maximum emails to return (default 10).

        Returns:
            dict with list of emails (id, subject, from, to, received_at,
            is_read, has_attachments, body_preview, web_link).
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        if not query or not query.strip():
            return {"status": "error", "message": "query must be a non-empty string."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)
            data = graph_get(
                sess,
                f"/users/{user_email}/messages",
                params={
                    "$search": f'"{query}"',
                    "$top": max_results,
                    "$select": (
                        "id,subject,from,toRecipients,ccRecipients,receivedDateTime,"
                        "isRead,hasAttachments,importance,bodyPreview,webLink"
                    ),
                },
            )
            messages = [
                {
                    "id": m.get("id", ""),
                    "subject": m.get("subject", ""),
                    "from": (m.get("from", {}).get("emailAddress", {}) or {}).get("address", ""),
                    "from_name": (m.get("from", {}).get("emailAddress", {}) or {}).get("name", ""),
                    "to": [r.get("emailAddress", {}).get("address", "") for r in m.get("toRecipients", [])],
                    "received_at": m.get("receivedDateTime", ""),
                    "is_read": m.get("isRead", False),
                    "has_attachments": m.get("hasAttachments", False),
                    "importance": m.get("importance", "normal"),
                    "body_preview": m.get("bodyPreview", ""),
                    "web_link": m.get("webLink", ""),
                }
                for m in data.get("value", [])
            ]
            return {"emails": messages, "count": len(messages)}
        except Exception as exc:
            logger.error("search_outlook_emails error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_outlook_emails(
        folder: str = "inbox",
        max_results: int = 10,
        unread_only: bool = False,
    ) -> dict:
        """List recent emails from an Outlook mail folder.

        Use this to check recent mail — what arrived today, unread messages,
        or the latest emails in Sent Items or a specific folder.

        Args:
            folder: Mail folder name. Common values:
                    'inbox'     — Inbox (default)
                    'sentitems' — Sent Items
                    'drafts'    — Drafts
                    'deleteditems' — Deleted Items
                    Or a folder display name like 'Archive'.
            max_results: Maximum emails to return (default 10).
            unread_only: If True, return only unread emails (default False).

        Returns:
            dict with list of emails (id, subject, from, received_at,
            is_read, has_attachments, body_preview, web_link).
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)

            params: dict = {
                "$top": max_results,
                "$orderby": "receivedDateTime desc",
                "$select": (
                    "id,subject,from,toRecipients,receivedDateTime,"
                    "isRead,hasAttachments,importance,bodyPreview,webLink"
                ),
            }
            if unread_only:
                params["$filter"] = "isRead eq false"

            data = graph_get(
                sess,
                f"/users/{user_email}/mailFolders/{folder}/messages",
                params=params,
            )
            messages = [
                {
                    "id": m.get("id", ""),
                    "subject": m.get("subject", ""),
                    "from": (m.get("from", {}).get("emailAddress", {}) or {}).get("address", ""),
                    "from_name": (m.get("from", {}).get("emailAddress", {}) or {}).get("name", ""),
                    "to": [r.get("emailAddress", {}).get("address", "") for r in m.get("toRecipients", [])],
                    "received_at": m.get("receivedDateTime", ""),
                    "is_read": m.get("isRead", False),
                    "has_attachments": m.get("hasAttachments", False),
                    "importance": m.get("importance", "normal"),
                    "body_preview": m.get("bodyPreview", ""),
                    "web_link": m.get("webLink", ""),
                }
                for m in data.get("value", [])
            ]
            return {"emails": messages, "count": len(messages), "folder": folder}
        except Exception as exc:
            logger.error("list_outlook_emails error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_outlook_email(email_id: str) -> dict:
        """Get the full content of a specific Outlook email.

        Use this after search_outlook_emails or list_outlook_emails to read
        the complete body of an email. HTML is stripped to plain text.

        Args:
            email_id: Email message ID from search or list results.

        Returns:
            dict with subject, from, from_name, to, cc, received_at, is_read,
            has_attachments, importance, web_link, body (plain text),
            and body_truncated flag.
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)
            msg = graph_get(
                sess,
                f"/users/{user_email}/messages/{email_id}",
                params={
                    "$select": (
                        "id,subject,from,toRecipients,ccRecipients,receivedDateTime,"
                        "isRead,hasAttachments,importance,body,webLink,bodyPreview"
                    )
                },
            )
            return _format_message(msg)
        except Exception as exc:
            logger.error("get_outlook_email error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [search_outlook_emails, list_outlook_emails, get_outlook_email]
