"""Outlook tool — Microsoft Graph API v1.0 integration (Mail).

Required credentials (set in tools_config.json or env vars):
  tenant_id     : Azure AD tenant ID
  client_id     : App registration client ID
  client_secret : App registration client secret (use env:OUTLOOK_CLIENT_SECRET)
  user_email    : The mailbox/UPN of the user whose mail to access
                  (e.g. riya@stratova.ai)

Azure AD app registration requirements:
  Permission type : Application (not Delegated)
  Permissions     : Mail.ReadWrite, Mail.Send
                    (Previously Mail.Read — update in Azure AD app registration.)

In tools_config.json, reference secrets as:
  "client_secret": "env:OUTLOOK_CLIENT_SECRET"

Tools exported:
  READ
    search_outlook_emails    - search emails by keyword, sender, or subject
    list_outlook_emails      - list recent emails from a folder
    get_outlook_email        - get full content of a specific email

  CREATE / SEND
    send_outlook_email       - compose and send a new email
    reply_to_outlook_email   - reply to an email
    forward_outlook_email    - forward an email to new recipients
    create_outlook_draft     - save an email as a draft
    create_outlook_folder    - create a new mail folder

  UPDATE
    mark_outlook_email_read  - mark an email as read or unread
    move_outlook_email       - move an email to a different folder
    flag_outlook_email       - flag or unflag an email for follow-up

  DELETE
    delete_outlook_email     - permanently delete an email
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config
from tools.microsoft.graph_utils import (
    get_token,
    graph_delete,
    graph_get,
    graph_patch,
    graph_post,
    graph_session,
)

logger = logging.getLogger(__name__)

_MAX_BODY_CHARS = 20_000

# Well-known folder names accepted directly by the Graph API
_WELL_KNOWN_FOLDERS = {
    "inbox", "sentitems", "drafts", "deleteditems", "archive",
    "junkemail", "outbox", "recoverableitemsdeletions", "searchfolders",
}


def _resolve_outlook_folder(sess, user_email: str, folder: str) -> "str | dict":
    """Resolve an Outlook folder display name to a folder ID or well-known name.

    Returns the folder identifier string on success, or an error/needs_clarification dict.
    """
    val = folder.strip()
    if val.lower() in _WELL_KNOWN_FOLDERS:
        return val.lower()
    # Long alphanumeric Graph API IDs — use directly
    if len(val) > 30:
        return val
    try:
        data = graph_get(
            sess,
            f"/users/{user_email}/mailFolders",
            params={"$top": 100, "$select": "id,displayName"},
        )
        folders = data.get("value", [])
    except Exception as exc:
        return {"status": "error", "message": f"Failed to list Outlook folders: {exc}"}
    exact = [f for f in folders if f.get("displayName", "").lower() == val.lower()]
    if exact:
        if len(exact) == 1:
            return exact[0]["id"]
        options = [{"id": f["id"], "display_name": f["displayName"]} for f in exact[:5]]
        return {"status": "needs_clarification", "message": f"Multiple folders named '{val}'. Please ask the user to pick one:", "options": options}
    partial = [f for f in folders if val.lower() in f.get("displayName", "").lower()]
    if not partial:
        return {"status": "error", "message": f"No Outlook folder found matching '{val}'. Use list_outlook_folders to see all folders."}
    if len(partial) == 1:
        return partial[0]["id"]
    options = [{"id": f["id"], "display_name": f["displayName"]} for f in partial[:5]]
    return {
        "status": "needs_clarification",
        "message": f"Multiple folders match '{val}'. Please ask the user to pick one:",
        "options": options,
    }


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


def _build_recipients(addresses: str) -> list[dict]:
    """Convert a comma-separated address string to Graph API recipient objects."""
    return [
        {"emailAddress": {"address": addr.strip()}}
        for addr in addresses.split(",")
        if addr.strip()
    ]


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def search_outlook_emails(query: str, max_results: int = 10) -> dict:
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
        or the latest emails in Sent Items or a specific folder. Accepts a
        well-known folder name, a display name, or a folder ID.

        Args:
            folder: Mail folder. Well-known values: 'inbox', 'sentitems',
                    'drafts', 'deleteditems', 'archive'. Or a custom folder
                    display name (e.g. 'Projects') — resolved automatically.
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

            resolved_folder = _resolve_outlook_folder(sess, user_email, folder)
            if isinstance(resolved_folder, dict):
                return resolved_folder

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
                f"/users/{user_email}/mailFolders/{resolved_folder}/messages",
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

    # ── CREATE / SEND ─────────────────────────────────────────────────────────

    def send_outlook_email(
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        importance: str = "normal",
        body_type: str = "Text",
    ) -> dict:
        """Compose and send a new Outlook email.

        Args:
            to: Recipient email address or comma-separated list.
            subject: Email subject line.
            body: Email body content.
            cc: CC recipients — comma-separated email addresses. Optional.
            bcc: BCC recipients — comma-separated email addresses. Optional.
            importance: 'low', 'normal' (default), or 'high'.
            body_type: 'Text' (default, plain text) or 'HTML' for rich content.

        Returns:
            dict confirming the email was sent.
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)

            message: dict = {
                "subject": subject,
                "body": {"contentType": body_type, "content": body},
                "toRecipients": _build_recipients(to),
                "importance": importance,
            }
            if cc:
                message["ccRecipients"] = _build_recipients(cc)
            if bcc:
                message["bccRecipients"] = _build_recipients(bcc)

            graph_post(sess, f"/users/{user_email}/sendMail", json_body={"message": message})
            return {"status": "sent", "to": to, "subject": subject}
        except Exception as exc:
            logger.error("send_outlook_email error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def reply_to_outlook_email(
        email_id: str,
        body: str,
        reply_all: bool = False,
        body_type: str = "Text",
    ) -> dict:
        """Reply to an Outlook email.

        Args:
            email_id: Email ID to reply to (from search or list results).
            body: Reply body text.
            reply_all: If True, replies to all recipients. Default is reply-to-sender only.
            body_type: 'Text' (default) or 'HTML'.

        Returns:
            dict confirming the reply was sent.
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)

            endpoint = "replyAll" if reply_all else "reply"
            graph_post(
                sess,
                f"/users/{user_email}/messages/{email_id}/{endpoint}",
                json_body={"message": {"body": {"contentType": body_type, "content": body}}},
            )
            return {"status": "replied", "email_id": email_id, "reply_all": reply_all}
        except Exception as exc:
            logger.error("reply_to_outlook_email error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def forward_outlook_email(email_id: str, to: str, comment: str = "") -> dict:
        """Forward an Outlook email to new recipients.

        Args:
            email_id: Email ID to forward.
            to: Forward recipient(s) — comma-separated email addresses.
            comment: Optional comment to prepend to the forwarded message body.

        Returns:
            dict confirming the forward was sent.
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)

            body: dict = {"toRecipients": _build_recipients(to)}
            if comment:
                body["comment"] = comment

            graph_post(
                sess,
                f"/users/{user_email}/messages/{email_id}/forward",
                json_body=body,
            )
            return {"status": "forwarded", "email_id": email_id, "to": to}
        except Exception as exc:
            logger.error("forward_outlook_email error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_outlook_draft(
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        body_type: str = "Text",
    ) -> dict:
        """Save an email as an Outlook draft without sending it.

        Args:
            to: Recipient email address(es) — comma-separated.
            subject: Email subject line.
            body: Email body content.
            cc: CC recipients (comma-separated). Optional.
            bcc: BCC recipients (comma-separated). Optional.
            body_type: 'Text' (default) or 'HTML'.

        Returns:
            dict with draft message id, subject, and status.
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)

            message: dict = {
                "subject": subject,
                "body": {"contentType": body_type, "content": body},
                "toRecipients": _build_recipients(to),
            }
            if cc:
                message["ccRecipients"] = _build_recipients(cc)
            if bcc:
                message["bccRecipients"] = _build_recipients(bcc)

            result = graph_post(sess, f"/users/{user_email}/messages", json_body=message)
            return {
                "id": result.get("id", ""),
                "subject": subject,
                "status": "draft_created",
            }
        except Exception as exc:
            logger.error("create_outlook_draft error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_outlook_folder(folder_name: str, parent_folder: str = "inbox") -> dict:
        """Create a new mail folder in Outlook.

        Args:
            folder_name: Display name for the new folder.
            parent_folder: Parent folder well-known name or folder ID.
                           Common values: 'inbox', 'sentitems', 'drafts'.
                           Defaults to 'inbox'.

        Returns:
            dict with new folder id, display name, and status.
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)

            result = graph_post(
                sess,
                f"/users/{user_email}/mailFolders/{parent_folder}/childFolders",
                json_body={"displayName": folder_name},
            )
            return {
                "id": result.get("id", ""),
                "display_name": result.get("displayName", folder_name),
                "parent_folder": parent_folder,
                "status": "created",
            }
        except Exception as exc:
            logger.error("create_outlook_folder error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def mark_outlook_email_read(email_id: str, is_read: bool = True) -> dict:
        """Mark an Outlook email as read or unread.

        Args:
            email_id: Email message ID.
            is_read: True to mark as read (default), False to mark as unread.

        Returns:
            dict confirming the update.
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)
            graph_patch(
                sess,
                f"/users/{user_email}/messages/{email_id}",
                json_body={"isRead": is_read},
            )
            return {"id": email_id, "is_read": is_read, "status": "updated"}
        except Exception as exc:
            logger.error("mark_outlook_email_read error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def move_outlook_email(email_id: str, destination_folder: str) -> dict:
        """Move an Outlook email to a different folder.

        Accepts a well-known folder name, a custom folder display name, or a
        folder ID. Display names are resolved to IDs automatically. If multiple
        folders match the name, the options are returned for the user to pick.

        Args:
            email_id: Email message ID to move.
            destination_folder: Folder name or ID. Well-known: 'inbox',
                                 'sentitems', 'drafts', 'deleteditems', 'archive'.
                                 Custom folder display name also accepted.

        Returns:
            dict with the moved message id and new folder.
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)
            resolved_folder = _resolve_outlook_folder(sess, user_email, destination_folder)
            if isinstance(resolved_folder, dict):
                return resolved_folder
            result = graph_post(
                sess,
                f"/users/{user_email}/messages/{email_id}/move",
                json_body={"destinationId": resolved_folder},
            )
            return {
                "id": result.get("id", email_id),
                "destination_folder": destination_folder,
                "status": "moved",
            }
        except Exception as exc:
            logger.error("move_outlook_email error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def flag_outlook_email(email_id: str, flag: bool = True) -> dict:
        """Flag or unflag an Outlook email for follow-up.

        Args:
            email_id: Email message ID.
            flag: True to flag the message (default), False to unflag it.

        Returns:
            dict confirming the flag state.
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)
            flag_status = "flagged" if flag else "notFlagged"
            graph_patch(
                sess,
                f"/users/{user_email}/messages/{email_id}",
                json_body={"flag": {"flagStatus": flag_status}},
            )
            return {"id": email_id, "flagged": flag, "status": "updated"}
        except Exception as exc:
            logger.error("flag_outlook_email error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_outlook_email(email_id: str) -> dict:
        """Permanently delete an Outlook email.

        The email is moved to Deleted Items and can be recovered from there.
        To permanently remove it without recovery use the Outlook web interface.

        Args:
            email_id: Email message ID to delete.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)
            try:
                graph_delete(sess, f"/users/{user_email}/messages/{email_id}")
            except Exception:
                # Fall back to mailFolders endpoint if this is a folder ID not a message ID
                graph_delete(sess, f"/users/{user_email}/mailFolders/{email_id}")
            return {"id": email_id, "status": "deleted"}
        except Exception as exc:
            logger.error("delete_outlook_email error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_outlook_folders(include_child_folders: bool = False) -> dict:
        """List all mail folders in the Outlook mailbox.

        Use this to discover folder names and IDs before moving emails or
        creating sub-folders. Returns both well-known folders (Inbox, Sent,
        Drafts, etc.) and custom user-created folders.

        Args:
            include_child_folders: If True, also return sub-folders under each
                                   top-level folder. Default False.

        Returns:
            dict with a list of folders (id, display_name, unread_count,
            total_items, child_folder_count).
        """
        cfg = get_config().tools.get("outlook")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Outlook tool is currently disabled."}
        try:
            tenant_id, client_id, client_secret, user_email = _cfg_vals(cfg.config)
            token = get_token(tenant_id, client_id, client_secret)
            sess = graph_session(token)
            data = graph_get(
                sess,
                f"/users/{user_email}/mailFolders",
                params={
                    "$top": 100,
                    "$select": "id,displayName,unreadItemCount,totalItemCount,childFolderCount",
                    "includeHiddenFolders": "false",
                },
            )
            folders = [
                {
                    "id": f.get("id", ""),
                    "display_name": f.get("displayName", ""),
                    "unread_count": f.get("unreadItemCount", 0),
                    "total_items": f.get("totalItemCount", 0),
                    "child_folder_count": f.get("childFolderCount", 0),
                }
                for f in data.get("value", [])
            ]
            return {"folders": folders, "count": len(folders)}
        except Exception as exc:
            logger.error("list_outlook_folders error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        search_outlook_emails,
        list_outlook_emails,
        get_outlook_email,
        list_outlook_folders,
        # Create / Send
        send_outlook_email,
        reply_to_outlook_email,
        forward_outlook_email,
        create_outlook_draft,
        create_outlook_folder,
        # Update
        mark_outlook_email_read,
        move_outlook_email,
        flag_outlook_email,
        # Delete
        delete_outlook_email,
    ]
