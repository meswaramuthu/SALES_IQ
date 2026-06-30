"""Gmail tool — service account with domain-wide delegation.

Setup (one-time, done by Google Workspace admin):
  1. Create a GCP service account and download the JSON key.
  2. Upload the key to GCS (set service_account_key_gcs_uri in tools_config.json).
  3. In Google Workspace Admin → Security → API controls → Domain-wide delegation,
     add the service account client ID with scopes:
       https://www.googleapis.com/auth/gmail.modify
       https://www.googleapis.com/auth/gmail.send
     (Previously only gmail.readonly — update the scopes in Admin Console to enable writes.)

Tools exported:
  READ
    search_gmail             - search messages using Gmail search syntax
    get_gmail_message        - get full body of a specific message

  CREATE / SEND
    send_gmail_message       - compose and send a new email
    reply_to_gmail_thread    - reply to an existing email thread
    create_gmail_draft       - save an email as a draft without sending

  UPDATE
    trash_gmail_message      - move a message to trash
    mark_gmail_message       - mark a message as read or unread
    add_gmail_label          - add a label to a message
    remove_gmail_label       - remove a label from a message
"""
from __future__ import annotations

import base64
import json
import logging
from email.mime.text import MIMEText
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)

_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

# System label IDs that are always valid without lookup
_GMAIL_SYSTEM_LABELS = {
    "INBOX", "STARRED", "IMPORTANT", "SENT", "TRASH", "SPAM", "UNREAD",
    "CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS",
    "CATEGORY_UPDATES", "CATEGORY_FORUMS",
}


def _resolve_label(service, label_id_or_name: str) -> "str | dict":
    """Resolve a Gmail label name or system label ID to a label ID.

    Returns the label ID string on success, or an error/needs_clarification dict.
    """
    val = label_id_or_name.strip()
    if val in _GMAIL_SYSTEM_LABELS or val.startswith("Label_"):
        return val
    try:
        result = service.users().labels().list(userId="me").execute()
        labels = result.get("labels", [])
        exact = [l for l in labels if l.get("name", "").lower() == val.lower()]
        if exact:
            return exact[0]["id"] if len(exact) == 1 else _label_options(exact, val)
        partial = [l for l in labels if val.lower() in l.get("name", "").lower()]
        if not partial:
            return {"status": "error", "message": f"No Gmail label found matching '{val}'. Use list_gmail_labels to see all labels."}
        if len(partial) == 1:
            return partial[0]["id"]
        return _label_options(partial[:5], val)
    except Exception as exc:
        return {"status": "error", "message": f"Failed to look up label '{val}': {exc}"}


def _label_options(labels: list, query: str) -> dict:
    options = [{"id": l["id"], "name": l["name"], "type": l.get("type", "")} for l in labels]
    return {
        "status": "needs_clarification",
        "message": f"Multiple labels match '{query}'. Please ask the user to pick one:",
        "options": options,
    }


def _build_service(cfg: dict):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    from tools.utils.gcs_utils import read_gcs_bytes

    key_info = json.loads(read_gcs_bytes(cfg["service_account_key_gcs_uri"]))
    creds = service_account.Credentials.from_service_account_info(
        key_info,
        scopes=_GMAIL_SCOPES,
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


def _build_mime_message(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    is_html: bool = False,
) -> dict:
    """Build a Gmail API message payload from email fields."""
    subtype = "html" if is_html else "plain"
    msg = MIMEText(body, subtype)
    msg["to"] = to
    msg["subject"] = subject
    if cc:
        msg["cc"] = cc
    if bcc:
        msg["bcc"] = bcc
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    return {"raw": raw}


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

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
                        "thread_id": meta.get("threadId", ""),
                        "subject": hdrs.get("Subject", "(no subject)"),
                        "from": hdrs.get("From", ""),
                        "date": hdrs.get("Date", ""),
                        "snippet": meta.get("snippet", ""),
                        "web_link": f"https://mail.google.com/mail/u/0/#all/{msg['id']}",
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
            dict with subject, from, to, date, thread_id, and full body text.
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
                "thread_id": msg.get("threadId", ""),
                "subject": hdrs.get("Subject", ""),
                "from": hdrs.get("From", ""),
                "to": hdrs.get("To", ""),
                "date": hdrs.get("Date", ""),
                "body": _extract_body(msg.get("payload", {})),
            }
        except Exception as exc:
            logger.error("Gmail get_message error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE / SEND ─────────────────────────────────────────────────────────

    def send_gmail_message(
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
    ) -> dict:
        """Compose and send a new Gmail email.

        Args:
            to: Recipient email address or comma-separated list
                (e.g. 'alice@company.com' or 'alice@c.com, bob@c.com').
            subject: Email subject line.
            body: Email body as plain text.
            cc: CC recipients — comma-separated email addresses. Optional.
            bcc: BCC recipients — comma-separated email addresses. Optional.

        Returns:
            dict with sent message id, thread_id, and status.
        """
        cfg = get_config().tools.get("gmail")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Gmail tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            message = _build_mime_message(to, subject, body, cc=cc, bcc=bcc)
            result = service.users().messages().send(userId="me", body=message).execute()
            return {
                "id": result.get("id", ""),
                "thread_id": result.get("threadId", ""),
                "status": "sent",
            }
        except Exception as exc:
            logger.error("Gmail send error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def reply_to_gmail_thread(
        thread_id: str,
        body: str,
        to: str = "",
        subject_prefix: str = "Re: ",
    ) -> dict:
        """Reply to an existing Gmail thread.

        Fetches the last message in the thread to extract recipient and subject,
        then sends a reply in the same thread.

        Args:
            thread_id: Gmail thread ID from search_gmail (threadId field).
            body: Reply body as plain text.
            to: Override the reply-to address. If blank, replies to the
                sender of the last message in the thread.
            subject_prefix: Prefix for the subject (default 'Re: '). Change
                            to 'Fwd: ' for a forward-style subject or '' for none.

        Returns:
            dict with sent message id, thread_id, and status.
        """
        cfg = get_config().tools.get("gmail")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Gmail tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            thread = service.users().threads().get(
                userId="me", id=thread_id, format="metadata",
                metadataHeaders=["Subject", "From", "Message-ID"],
            ).execute()

            messages = thread.get("messages", [])
            last_msg = messages[-1] if messages else {}
            hdrs = {
                h["name"]: h["value"]
                for h in last_msg.get("payload", {}).get("headers", [])
            }

            reply_to = to or hdrs.get("From", "")
            original_subject = hdrs.get("Subject", "")
            reply_subject = (
                original_subject if original_subject.startswith(subject_prefix)
                else f"{subject_prefix}{original_subject}"
            )

            message = _build_mime_message(reply_to, reply_subject, body)
            message["threadId"] = thread_id

            result = service.users().messages().send(userId="me", body=message).execute()
            return {
                "id": result.get("id", ""),
                "thread_id": thread_id,
                "replied_to": reply_to,
                "status": "sent",
            }
        except Exception as exc:
            logger.error("Gmail reply error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_gmail_draft(
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
    ) -> dict:
        """Save an email as a Gmail draft without sending it.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Email body as plain text.
            cc: CC recipients (comma-separated). Optional.
            bcc: BCC recipients (comma-separated). Optional.

        Returns:
            dict with draft id, message id, and status.
        """
        cfg = get_config().tools.get("gmail")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Gmail tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            message = _build_mime_message(to, subject, body, cc=cc, bcc=bcc)
            draft = service.users().drafts().create(
                userId="me",
                body={"message": message},
            ).execute()
            return {
                "draft_id": draft.get("id", ""),
                "message_id": draft.get("message", {}).get("id", ""),
                "status": "draft_created",
            }
        except Exception as exc:
            logger.error("Gmail create_draft error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def trash_gmail_message(message_id: str) -> dict:
        """Move a Gmail message to trash.

        The message can be recovered from the Gmail trash within 30 days.

        Args:
            message_id: Gmail message ID to trash.

        Returns:
            dict confirming the message was moved to trash.
        """
        cfg = get_config().tools.get("gmail")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Gmail tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            service.users().messages().trash(userId="me", id=message_id).execute()
            return {"id": message_id, "status": "trashed"}
        except Exception as exc:
            logger.error("Gmail trash error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def mark_gmail_message(message_id: str, mark_as: str = "read") -> dict:
        """Mark a Gmail message as read or unread.

        Args:
            message_id: Gmail message ID to mark.
            mark_as: 'read' (default) or 'unread'.

        Returns:
            dict confirming the update.
        """
        cfg = get_config().tools.get("gmail")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Gmail tool is currently disabled."}
        if mark_as not in ("read", "unread"):
            return {"status": "error", "message": "mark_as must be 'read' or 'unread'."}
        try:
            service = _build_service(cfg.config)
            if mark_as == "read":
                body = {"removeLabelIds": ["UNREAD"]}
            else:
                body = {"addLabelIds": ["UNREAD"]}
            service.users().messages().modify(
                userId="me", id=message_id, body=body
            ).execute()
            return {"id": message_id, "status": mark_as}
        except Exception as exc:
            logger.error("Gmail mark error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_gmail_labels() -> dict:
        """List all Gmail labels — both system labels and custom user-created ones.

        Use this to discover available label names and IDs before calling
        add_gmail_label or remove_gmail_label with a custom label.

        Returns:
            dict with a list of labels (id, name, type — 'system' or 'user').
        """
        cfg = get_config().tools.get("gmail")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Gmail tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            result = service.users().labels().list(userId="me").execute()
            labels = [
                {"id": l["id"], "name": l["name"], "type": l.get("type", "")}
                for l in result.get("labels", [])
            ]
            return {"labels": labels, "count": len(labels)}
        except Exception as exc:
            logger.error("Gmail list_labels error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_gmail_label(message_id: str, label_id: str) -> dict:
        """Add a label to a Gmail message.

        Accepts a label name (e.g. 'Work', 'Receipts') or a label ID
        (e.g. 'STARRED', 'Label_12345'). Label names are resolved to IDs
        automatically. If multiple labels match the name, the options are
        returned for the user to choose from.

        Args:
            message_id: Gmail message ID.
            label_id: Label name or ID. System labels: 'STARRED', 'IMPORTANT',
                      'INBOX', 'SPAM'. For custom labels use the label name
                      (e.g. 'Work') or use list_gmail_labels to see all labels.

        Returns:
            dict confirming the label was added.
        """
        cfg = get_config().tools.get("gmail")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Gmail tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            resolved = _resolve_label(service, label_id)
            if isinstance(resolved, dict):
                return resolved
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [resolved]},
            ).execute()
            return {"id": message_id, "label_added": resolved, "label_name": label_id, "status": "labeled"}
        except Exception as exc:
            logger.error("Gmail add_label error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def remove_gmail_label(message_id: str, label_id: str) -> dict:
        """Remove a label from a Gmail message.

        Accepts a label name or label ID. Label names are resolved automatically.
        If multiple labels match the name, the options are returned for the
        user to choose from.

        Args:
            message_id: Gmail message ID.
            label_id: Label name or ID to remove (e.g. 'Work', 'STARRED').

        Returns:
            dict confirming the label was removed.
        """
        cfg = get_config().tools.get("gmail")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Gmail tool is currently disabled."}
        try:
            service = _build_service(cfg.config)
            resolved = _resolve_label(service, label_id)
            if isinstance(resolved, dict):
                return resolved
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": [resolved]},
            ).execute()
            return {"id": message_id, "label_removed": resolved, "label_name": label_id, "status": "label_removed"}
        except Exception as exc:
            logger.error("Gmail remove_label error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        search_gmail,
        get_gmail_message,
        # Create / Send
        send_gmail_message,
        reply_to_gmail_thread,
        create_gmail_draft,
        # Update
        trash_gmail_message,
        mark_gmail_message,
        add_gmail_label,
        remove_gmail_label,
        list_gmail_labels,
    ]
