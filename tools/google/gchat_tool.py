"""Google Chat tool — Google Chat API v1 via google-api-python-client.

Required credentials (set in tools_config.json or env vars):
  credentials_json : Path to service account JSON file, OR
  access_token     : Short-lived OAuth2 access token
  Use service account with the Chat API scope:
    https://www.googleapis.com/auth/chat.messages
    https://www.googleapis.com/auth/chat.spaces

In tools_config.json, reference secrets as:
  "credentials_json": "env:GCHAT_CREDENTIALS_JSON"
  "access_token":     "env:GCHAT_ACCESS_TOKEN"

Tools exported:
  READ
    list_gchat_spaces         - list all Chat spaces/rooms the app belongs to
    get_gchat_space           - get metadata for a specific space
    list_gchat_messages       - list messages in a space (with optional filter)
    get_gchat_message         - get a single message by resource name
    list_gchat_members        - list members of a space

  CREATE
    create_gchat_message      - send a new message to a space or DM
    create_gchat_space        - create a new named space
    add_gchat_member          - add a user to a space

  UPDATE
    update_gchat_message      - edit text of an existing message

  DELETE
    delete_gchat_message      - delete a message
    remove_gchat_member       - remove a member from a space
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _service(cfg: dict):
    import google.auth
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = [
        "https://www.googleapis.com/auth/chat.messages",
        "https://www.googleapis.com/auth/chat.spaces",
        "https://www.googleapis.com/auth/chat.memberships",
    ]

    creds_json = cfg.get("credentials_json", "")
    access_token = cfg.get("access_token", "")

    if creds_json:
        if creds_json.startswith("{"):
            info = json.loads(creds_json)
        else:
            with open(creds_json) as f:
                info = json.load(f)
        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    elif access_token:
        from google.oauth2.credentials import Credentials
        creds = Credentials(token=access_token)
    else:
        creds, _ = google.auth.default(scopes=scopes)

    return build("chat", "v1", credentials=creds, cache_discovery=False)


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_gchat_spaces(page_size: int = 20) -> dict:
        """List all Google Chat spaces the app or service account belongs to.

        Returns spaces of all types: rooms, DMs, and group DMs.

        Args:
            page_size: Maximum number of spaces to return (default 20, max 1000).

        Returns:
            dict with list of spaces (name, displayName, type, spaceType).
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            result = svc.spaces().list(pageSize=page_size).execute()
            spaces = [
                {
                    "name": s.get("name", ""),
                    "display_name": s.get("displayName", ""),
                    "type": s.get("type", ""),
                    "space_type": s.get("spaceType", ""),
                    "single_user_bot_dm": s.get("singleUserBotDm", False),
                }
                for s in result.get("spaces", [])
            ]
            return {"spaces": spaces, "count": len(spaces)}
        except Exception as exc:
            logger.error("GChat list_spaces error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_gchat_space(space_name: str) -> dict:
        """Get metadata for a specific Google Chat space.

        Args:
            space_name: Space resource name (e.g. 'spaces/AABBcc123').

        Returns:
            dict with space name, displayName, type, memberCount, and adminInstalled.
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            s = svc.spaces().get(name=space_name).execute()
            return {
                "name": s.get("name", ""),
                "display_name": s.get("displayName", ""),
                "type": s.get("type", ""),
                "space_type": s.get("spaceType", ""),
                "admin_installed": s.get("adminInstalled", False),
            }
        except Exception as exc:
            logger.error("GChat get_space error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_gchat_messages(space_name: str, page_size: int = 25, filter_str: str = "") -> dict:
        """List messages in a Google Chat space, optionally filtered.

        Args:
            space_name: Space resource name (e.g. 'spaces/AABBcc123').
            page_size: Maximum number of messages to return (default 25).
            filter_str: Optional filter expression, e.g.
                        'createTime > "2024-01-01T00:00:00Z"'
                        'sender.type = "HUMAN"'

        Returns:
            dict with list of messages (name, text, sender, createTime).
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            kwargs: dict = {"parent": space_name, "pageSize": page_size}
            if filter_str:
                kwargs["filter"] = filter_str
            result = svc.spaces().messages().list(**kwargs).execute()
            messages = [
                {
                    "name": m.get("name", ""),
                    "text": m.get("text", ""),
                    "sender": m.get("sender", {}).get("displayName", ""),
                    "sender_type": m.get("sender", {}).get("type", ""),
                    "create_time": m.get("createTime", ""),
                    "thread": m.get("thread", {}).get("name", ""),
                }
                for m in result.get("messages", [])
            ]
            return {"messages": messages, "count": len(messages)}
        except Exception as exc:
            logger.error("GChat list_messages error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_gchat_message(message_name: str) -> dict:
        """Get a single Google Chat message by its resource name.

        Args:
            message_name: Full message resource name
                          (e.g. 'spaces/AABBcc123/messages/xyz').

        Returns:
            dict with message text, sender, createTime, and any attached cards.
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            m = svc.spaces().messages().get(name=message_name).execute()
            return {
                "name": m.get("name", ""),
                "text": m.get("text", ""),
                "sender": m.get("sender", {}).get("displayName", ""),
                "sender_type": m.get("sender", {}).get("type", ""),
                "create_time": m.get("createTime", ""),
                "last_update_time": m.get("lastUpdateTime", ""),
                "thread": m.get("thread", {}).get("name", ""),
                "has_cards": bool(m.get("cardsV2")),
            }
        except Exception as exc:
            logger.error("GChat get_message error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_gchat_members(space_name: str, page_size: int = 50) -> dict:
        """List members of a Google Chat space.

        Args:
            space_name: Space resource name (e.g. 'spaces/AABBcc123').
            page_size: Maximum number of members to return (default 50).

        Returns:
            dict with list of members (name, displayName, role, type).
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            result = svc.spaces().members().list(parent=space_name, pageSize=page_size).execute()
            members = [
                {
                    "name": mem.get("name", ""),
                    "display_name": mem.get("member", {}).get("displayName", ""),
                    "email": mem.get("member", {}).get("name", ""),
                    "type": mem.get("member", {}).get("type", ""),
                    "role": mem.get("role", ""),
                    "state": mem.get("state", ""),
                }
                for mem in result.get("memberships", [])
            ]
            return {"members": members, "count": len(members)}
        except Exception as exc:
            logger.error("GChat list_members error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_gchat_message(
        space_name: str,
        text: str,
        thread_name: str = "",
    ) -> dict:
        """Send a new text message to a Google Chat space or DM.

        Args:
            space_name: Space resource name (e.g. 'spaces/AABBcc123').
            text: Message body (supports basic markdown formatting).
            thread_name: Optional thread resource name to reply in-thread
                         (e.g. 'spaces/AABBcc123/threads/xyz'). Leave blank
                         to start a new thread.

        Returns:
            dict with created message name, text, and createTime.
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            body: dict = {"text": text}
            kwargs: dict = {"parent": space_name, "body": body}
            if thread_name:
                body["thread"] = {"name": thread_name}
                kwargs["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
            msg = svc.spaces().messages().create(**kwargs).execute()
            return {
                "name": msg.get("name", ""),
                "text": msg.get("text", ""),
                "create_time": msg.get("createTime", ""),
                "thread": msg.get("thread", {}).get("name", ""),
                "status": "sent",
            }
        except Exception as exc:
            logger.error("GChat create_message error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_gchat_space(display_name: str, space_type: str = "SPACE") -> dict:
        """Create a new Google Chat space.

        Args:
            display_name: Human-readable name of the space (e.g. 'Engineering Alerts').
            space_type: Type of space — 'SPACE' (named room) or 'GROUP_CHAT'.
                        Default 'SPACE'.

        Returns:
            dict with created space name and displayName.
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            body = {"displayName": display_name, "spaceType": space_type}
            space = svc.spaces().create(body=body).execute()
            return {
                "name": space.get("name", ""),
                "display_name": space.get("displayName", ""),
                "space_type": space.get("spaceType", ""),
                "status": "created",
            }
        except Exception as exc:
            logger.error("GChat create_space error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_gchat_member(space_name: str, user_name: str, role: str = "ROLE_MEMBER") -> dict:
        """Add a user to a Google Chat space.

        Args:
            space_name: Space resource name (e.g. 'spaces/AABBcc123').
            user_name: User resource name (e.g. 'users/123456789') or email
                       in the format 'users/{userId}'.
            role: Member role — 'ROLE_MEMBER' or 'ROLE_MANAGER'. Default 'ROLE_MEMBER'.

        Returns:
            dict with membership name and role.
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            body = {"member": {"name": user_name, "type": "HUMAN"}, "role": role}
            mem = svc.spaces().members().create(parent=space_name, body=body).execute()
            return {
                "name": mem.get("name", ""),
                "role": mem.get("role", ""),
                "state": mem.get("state", ""),
                "status": "added",
            }
        except Exception as exc:
            logger.error("GChat add_member error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_gchat_message(message_name: str, text: str) -> dict:
        """Edit the text of an existing Google Chat message.

        Only the message text is updated; cards and attachments are unchanged.

        Args:
            message_name: Full message resource name
                          (e.g. 'spaces/AABBcc123/messages/xyz').
            text: New message text.

        Returns:
            dict with updated message name and new text.
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            body = {"text": text}
            msg = svc.spaces().messages().update(
                name=message_name,
                body=body,
                updateMask="text",
            ).execute()
            return {
                "name": msg.get("name", ""),
                "text": msg.get("text", ""),
                "last_update_time": msg.get("lastUpdateTime", ""),
                "status": "updated",
            }
        except Exception as exc:
            logger.error("GChat update_message error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_gchat_message(message_name: str) -> dict:
        """Delete a Google Chat message.

        The app or service account must be the sender or have space manager rights.

        Args:
            message_name: Full message resource name
                          (e.g. 'spaces/AABBcc123/messages/xyz').

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            svc.spaces().messages().delete(name=message_name).execute()
            return {"name": message_name, "status": "deleted"}
        except Exception as exc:
            logger.error("GChat delete_message error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def remove_gchat_member(membership_name: str) -> dict:
        """Remove a member from a Google Chat space.

        Args:
            membership_name: Membership resource name
                             (e.g. 'spaces/AABBcc123/members/456').

        Returns:
            dict confirming removal.
        """
        cfg = get_config().tools.get("gchat")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Google Chat tool is currently disabled."}
        try:
            svc = _service(cfg.config)
            svc.spaces().members().delete(name=membership_name).execute()
            return {"name": membership_name, "status": "removed"}
        except Exception as exc:
            logger.error("GChat remove_member error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_gchat_spaces,
        get_gchat_space,
        list_gchat_messages,
        get_gchat_message,
        list_gchat_members,
        # Create
        create_gchat_message,
        create_gchat_space,
        add_gchat_member,
        # Update
        update_gchat_message,
        # Delete
        delete_gchat_message,
        remove_gchat_member,
    ]
