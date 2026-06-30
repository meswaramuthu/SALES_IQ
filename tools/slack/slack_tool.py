"""Slack tool — Slack Web API v2 via slack-sdk.

Required credentials (set in tools_config.json or env vars):
  bot_token : Slack Bot User OAuth Token (xoxb-...)
              Scopes needed:
                channels:read, channels:write, channels:history
                groups:read, groups:write, groups:history
                chat:write, chat:write.public
                users:read, files:write, reactions:write
                im:read, im:write

In tools_config.json, reference secrets as:
  "bot_token": "env:SLACK_BOT_TOKEN"

Tools exported:
  READ
    list_slack_channels       - list public and private channels
    get_slack_channel         - get info for a specific channel by ID or name
    get_slack_channel_history - list recent messages in a channel
    get_slack_message         - get a specific message by channel + timestamp
    list_slack_users          - list workspace users

  CREATE
    send_slack_message        - post a message to a channel or DM
    create_slack_channel      - create a new public or private channel
    send_slack_dm             - open a DM and send a message to a user
    add_slack_reaction        - add an emoji reaction to a message

  UPDATE
    update_slack_message      - edit an existing message
    invite_to_slack_channel   - invite users to a channel
    set_slack_channel_topic   - set the topic of a channel

  DELETE
    delete_slack_message      - delete a message (must be from the bot)
    archive_slack_channel     - archive a channel
    remove_slack_reaction     - remove an emoji reaction from a message
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _client(cfg: dict):
    from slack_sdk import WebClient
    return WebClient(token=cfg.get("bot_token", ""))


def _resolve_channel(client, channel: str) -> str:
    """Return channel ID — pass-through if already looks like an ID (Cxxxxxxxx)."""
    if channel.startswith("C") and len(channel) >= 9:
        return channel
    resp = client.conversations_list(types="public_channel,private_channel", limit=200)
    for ch in resp["channels"]:
        if ch.get("name") == channel.lstrip("#"):
            return ch["id"]
    return channel


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_slack_channels(limit: int = 50, include_private: bool = False) -> dict:
        """List Slack channels the bot has access to.

        Args:
            limit: Maximum number of channels to return (default 50).
            include_private: If True, include private channels the bot is in.

        Returns:
            dict with list of channels (id, name, is_private, topic, member_count).
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            types = "public_channel,private_channel" if include_private else "public_channel"
            resp = client.conversations_list(types=types, limit=limit)
            channels = [
                {
                    "id": ch["id"],
                    "name": ch.get("name", ""),
                    "is_private": ch.get("is_private", False),
                    "is_archived": ch.get("is_archived", False),
                    "topic": ch.get("topic", {}).get("value", ""),
                    "member_count": ch.get("num_members", 0),
                }
                for ch in resp.get("channels", [])
            ]
            return {"channels": channels, "count": len(channels)}
        except Exception as exc:
            logger.error("Slack list_channels error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_slack_channel(channel: str) -> dict:
        """Get info for a Slack channel by ID or name.

        Args:
            channel: Channel ID (C0XXXXXX) or name (e.g. 'general').

        Returns:
            dict with channel id, name, topic, purpose, member_count, is_private.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            channel_id = _resolve_channel(client, channel)
            resp = client.conversations_info(channel=channel_id)
            ch = resp["channel"]
            return {
                "id": ch["id"],
                "name": ch.get("name", ""),
                "is_private": ch.get("is_private", False),
                "is_archived": ch.get("is_archived", False),
                "topic": ch.get("topic", {}).get("value", ""),
                "purpose": ch.get("purpose", {}).get("value", ""),
                "member_count": ch.get("num_members", 0),
                "created": ch.get("created", 0),
            }
        except Exception as exc:
            logger.error("Slack get_channel error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_slack_channel_history(channel: str, limit: int = 25) -> dict:
        """Get recent messages from a Slack channel.

        Args:
            channel: Channel ID (C0XXXXXX) or name (e.g. 'general').
            limit: Number of messages to retrieve (default 25, max 999).

        Returns:
            dict with list of messages (ts, text, user, type, thread_ts).
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            channel_id = _resolve_channel(client, channel)
            resp = client.conversations_history(channel=channel_id, limit=limit)
            messages = [
                {
                    "ts": m.get("ts", ""),
                    "text": m.get("text", ""),
                    "user": m.get("user", m.get("bot_id", "")),
                    "type": m.get("type", ""),
                    "thread_ts": m.get("thread_ts", ""),
                    "reply_count": m.get("reply_count", 0),
                }
                for m in resp.get("messages", [])
            ]
            return {"messages": messages, "count": len(messages), "channel_id": channel_id}
        except Exception as exc:
            logger.error("Slack channel_history error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_slack_message(channel: str, ts: str) -> dict:
        """Get a specific Slack message by channel and timestamp.

        Args:
            channel: Channel ID (C0XXXXXX) or name.
            ts: Message timestamp (e.g. '1684500000.123456') — used as message ID in Slack.

        Returns:
            dict with message text, user, reactions, and thread info.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            channel_id = _resolve_channel(client, channel)
            resp = client.conversations_history(
                channel=channel_id, latest=ts, oldest=ts, inclusive=True, limit=1
            )
            msgs = resp.get("messages", [])
            if not msgs:
                return {"status": "not_found", "message": f"No message found with ts={ts}"}
            m = msgs[0]
            return {
                "ts": m.get("ts", ""),
                "text": m.get("text", ""),
                "user": m.get("user", ""),
                "reactions": [
                    {"name": r["name"], "count": r["count"]}
                    for r in m.get("reactions", [])
                ],
                "thread_ts": m.get("thread_ts", ""),
                "reply_count": m.get("reply_count", 0),
            }
        except Exception as exc:
            logger.error("Slack get_message error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_slack_users(limit: int = 50) -> dict:
        """List users in the Slack workspace.

        Args:
            limit: Maximum number of users to return (default 50).

        Returns:
            dict with list of users (id, name, real_name, email, is_bot).
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            resp = client.users_list(limit=limit)
            users = [
                {
                    "id": u["id"],
                    "name": u.get("name", ""),
                    "real_name": u.get("real_name", ""),
                    "email": u.get("profile", {}).get("email", ""),
                    "is_bot": u.get("is_bot", False),
                    "is_admin": u.get("is_admin", False),
                    "deleted": u.get("deleted", False),
                }
                for u in resp.get("members", [])
                if not u.get("deleted")
            ]
            return {"users": users, "count": len(users)}
        except Exception as exc:
            logger.error("Slack list_users error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def send_slack_message(
        channel: str,
        text: str,
        thread_ts: str = "",
        mrkdwn: bool = True,
    ) -> dict:
        """Post a message to a Slack channel or thread.

        Args:
            channel: Channel ID (C0XXXXXX), channel name (e.g. 'general'),
                     or user ID for a DM.
            text: Message text. Supports Slack mrkdwn by default
                  (e.g. *bold*, _italic_, `code`, <URL|label>).
            thread_ts: Timestamp of a parent message to reply in-thread.
                       Leave blank to post as a new top-level message.
            mrkdwn: Whether to enable Slack markdown. Default True.

        Returns:
            dict with channel, ts (message ID), and permalink.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            kwargs: dict = {"channel": channel, "text": text, "mrkdwn": mrkdwn}
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
            resp = client.chat_postMessage(**kwargs)
            return {
                "channel": resp["channel"],
                "ts": resp["ts"],
                "thread_ts": resp.get("message", {}).get("thread_ts", ""),
                "status": "sent",
            }
        except Exception as exc:
            logger.error("Slack send_message error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_slack_channel(name: str, is_private: bool = False) -> dict:
        """Create a new Slack channel.

        Args:
            name: Channel name (lowercase, no spaces — use hyphens).
            is_private: Create as a private channel if True. Default False (public).

        Returns:
            dict with channel id, name, and type.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            resp = client.conversations_create(name=name, is_private=is_private)
            ch = resp["channel"]
            return {
                "id": ch["id"],
                "name": ch.get("name", ""),
                "is_private": ch.get("is_private", False),
                "status": "created",
            }
        except Exception as exc:
            logger.error("Slack create_channel error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def send_slack_dm(user_id: str, text: str) -> dict:
        """Open a DM with a user and send them a message.

        Args:
            user_id: Slack user ID (e.g. 'U0XXXXXX'). Use list_slack_users
                     to find user IDs by name or email.
            text: Message text.

        Returns:
            dict with channel (DM channel ID) and ts (message timestamp).
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            open_resp = client.conversations_open(users=user_id)
            dm_channel = open_resp["channel"]["id"]
            send_resp = client.chat_postMessage(channel=dm_channel, text=text)
            return {
                "channel": dm_channel,
                "ts": send_resp["ts"],
                "status": "sent",
            }
        except Exception as exc:
            logger.error("Slack send_dm error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_slack_reaction(channel: str, ts: str, emoji: str) -> dict:
        """Add an emoji reaction to a Slack message.

        Args:
            channel: Channel ID or name containing the message.
            ts: Message timestamp (e.g. '1684500000.123456').
            emoji: Emoji name without colons (e.g. 'thumbsup', 'white_check_mark').

        Returns:
            dict confirming the reaction was added.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            channel_id = _resolve_channel(client, channel)
            client.reactions_add(channel=channel_id, timestamp=ts, name=emoji)
            return {"channel": channel_id, "ts": ts, "emoji": emoji, "status": "reacted"}
        except Exception as exc:
            logger.error("Slack add_reaction error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_slack_message(channel: str, ts: str, text: str) -> dict:
        """Edit an existing Slack message.

        Only the bot that originally posted the message can edit it.

        Args:
            channel: Channel ID or name where the message is posted.
            ts: Message timestamp (the unique message ID).
            text: New message text.

        Returns:
            dict with channel, ts, and updated text.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            channel_id = _resolve_channel(client, channel)
            resp = client.chat_update(channel=channel_id, ts=ts, text=text)
            return {
                "channel": resp["channel"],
                "ts": resp["ts"],
                "text": resp.get("text", text),
                "status": "updated",
            }
        except Exception as exc:
            logger.error("Slack update_message error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def invite_to_slack_channel(channel: str, user_ids: list[str]) -> dict:
        """Invite one or more users to a Slack channel.

        Args:
            channel: Channel ID or name.
            user_ids: List of Slack user IDs to invite (e.g. ['U0AAAAAA', 'U0BBBBBB']).

        Returns:
            dict with channel name and list of invited user IDs.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            channel_id = _resolve_channel(client, channel)
            client.conversations_invite(channel=channel_id, users=",".join(user_ids))
            return {"channel": channel_id, "invited_users": user_ids, "status": "invited"}
        except Exception as exc:
            logger.error("Slack invite_to_channel error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def set_slack_channel_topic(channel: str, topic: str) -> dict:
        """Set the topic for a Slack channel.

        Args:
            channel: Channel ID or name.
            topic: New topic text (max 250 characters).

        Returns:
            dict with channel and new topic.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            channel_id = _resolve_channel(client, channel)
            resp = client.conversations_setTopic(channel=channel_id, topic=topic)
            return {
                "channel": channel_id,
                "topic": resp["topic"]["value"],
                "status": "updated",
            }
        except Exception as exc:
            logger.error("Slack set_topic error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_slack_message(channel: str, ts: str) -> dict:
        """Delete a Slack message.

        The bot must have chat:write scope and must be the message author,
        or the workspace must allow bots to delete others' messages.

        Args:
            channel: Channel ID or name.
            ts: Message timestamp (the unique message ID).

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            channel_id = _resolve_channel(client, channel)
            client.chat_delete(channel=channel_id, ts=ts)
            return {"channel": channel_id, "ts": ts, "status": "deleted"}
        except Exception as exc:
            logger.error("Slack delete_message error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def archive_slack_channel(channel: str) -> dict:
        """Archive a Slack channel (soft-delete — can be unarchived).

        Archived channels preserve message history but are hidden from the
        channel list. Members can no longer post.

        Args:
            channel: Channel ID or name.

        Returns:
            dict confirming the channel was archived.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            channel_id = _resolve_channel(client, channel)
            client.conversations_archive(channel=channel_id)
            return {"channel": channel_id, "status": "archived"}
        except Exception as exc:
            logger.error("Slack archive_channel error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def remove_slack_reaction(channel: str, ts: str, emoji: str) -> dict:
        """Remove an emoji reaction from a Slack message.

        Args:
            channel: Channel ID or name containing the message.
            ts: Message timestamp.
            emoji: Emoji name without colons (e.g. 'thumbsup').

        Returns:
            dict confirming the reaction was removed.
        """
        cfg = get_config().tools.get("slack")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Slack tool is currently disabled."}
        try:
            client = _client(cfg.config)
            channel_id = _resolve_channel(client, channel)
            client.reactions_remove(channel=channel_id, timestamp=ts, name=emoji)
            return {"channel": channel_id, "ts": ts, "emoji": emoji, "status": "removed"}
        except Exception as exc:
            logger.error("Slack remove_reaction error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_slack_channels,
        get_slack_channel,
        get_slack_channel_history,
        get_slack_message,
        list_slack_users,
        # Create
        send_slack_message,
        create_slack_channel,
        send_slack_dm,
        add_slack_reaction,
        # Update
        update_slack_message,
        invite_to_slack_channel,
        set_slack_channel_topic,
        # Delete
        delete_slack_message,
        archive_slack_channel,
        remove_slack_reaction,
    ]
