"""Zendesk tool — Zendesk REST API v2.

Required credentials (set in tools_config.json or env vars):
  subdomain : Your Zendesk subdomain (e.g. 'mycompany' for mycompany.zendesk.com)
  email     : Agent email address for basic auth
  api_token : Zendesk API token (Admin Center → Apps & Integrations → APIs → Zendesk API)

In tools_config.json, reference secrets as:
  "api_token": "env:ZENDESK_API_TOKEN"
  "email":     "env:ZENDESK_EMAIL"
  "subdomain": "env:ZENDESK_SUBDOMAIN"

Tools exported:
  READ
    list_zendesk_tickets      - list tickets with optional status/priority filter
    get_zendesk_ticket        - get a single ticket with comments
    search_zendesk_tickets    - search tickets using Zendesk query syntax
    list_zendesk_users        - list end users and agents
    get_zendesk_user          - get a single user by ID
    list_zendesk_groups       - list agent groups
    list_zendesk_macros       - list automation macros

  CREATE
    create_zendesk_ticket     - create a new support ticket
    add_zendesk_comment       - add a public or private comment to a ticket
    create_zendesk_user       - create a new end user

  UPDATE
    update_zendesk_ticket     - update ticket fields (status, assignee, priority...)
    update_zendesk_user       - update a user record
    apply_zendesk_macro       - apply a macro to a ticket

  DELETE
    delete_zendesk_ticket     - delete a ticket
    delete_zendesk_user       - permanently delete a user (GDPR)
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _session(cfg: dict):
    import requests
    subdomain = cfg.get("subdomain", "").rstrip("/")
    email = cfg.get("email", "")
    api_token = cfg.get("api_token", "")
    sess = requests.Session()
    sess.auth = (f"{email}/token", api_token)
    sess.headers.update({"Content-Type": "application/json"})
    base = f"https://{subdomain}.zendesk.com/api/v2"
    return sess, base


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_zendesk_tickets(
        status: str = "",
        assignee_id: int | None = None,
        page_size: int = 25,
    ) -> dict:
        """List Zendesk support tickets.

        Args:
            status: Filter by status — 'new', 'open', 'pending', 'hold',
                    'solved', 'closed'. Leave blank for all.
            assignee_id: Filter by agent (user) ID.
            page_size: Number of tickets to return (default 25, max 100).

        Returns:
            dict with list of tickets (id, subject, status, priority, requester, assignee).
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            if status or assignee_id is not None:
                query_parts = ["type:ticket"]
                if status:
                    query_parts.append(f"status:{status}")
                if assignee_id is not None:
                    query_parts.append(f"assignee_id:{assignee_id}")
                resp = sess.get(
                    f"{base}/search",
                    params={"query": " ".join(query_parts), "per_page": page_size},
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()
                raw_tickets = [t for t in data.get("results", []) if t.get("result_type") == "ticket"]
                has_more = len(raw_tickets) == page_size
            else:
                resp = sess.get(
                    f"{base}/tickets",
                    params={"page[size]": page_size, "sort": "-created_at"},
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()
                raw_tickets = data.get("tickets", [])
                has_more = data.get("meta", {}).get("has_more", False)
            tickets = [
                {
                    "id": t.get("id"),
                    "subject": t.get("subject", ""),
                    "status": t.get("status", ""),
                    "priority": t.get("priority", ""),
                    "requester_id": t.get("requester_id"),
                    "assignee_id": t.get("assignee_id"),
                    "group_id": t.get("group_id"),
                    "created_at": t.get("created_at", ""),
                    "updated_at": t.get("updated_at", ""),
                    "tags": t.get("tags", []),
                }
                for t in raw_tickets
            ]
            return {
                "tickets": tickets,
                "count": len(tickets),
                "has_more": has_more,
            }
        except Exception as exc:
            logger.error("Zendesk list_tickets error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_zendesk_ticket(ticket_id: int) -> dict:
        """Get a single Zendesk ticket with all comments.

        Args:
            ticket_id: Zendesk ticket ID (numeric).

        Returns:
            dict with ticket fields, description, and all comments.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            t_resp = sess.get(f"{base}/tickets/{ticket_id}", timeout=20)
            t_resp.raise_for_status()
            t = t_resp.json().get("ticket", {})
            c_resp = sess.get(f"{base}/tickets/{ticket_id}/comments", timeout=20)
            comments = []
            if c_resp.ok:
                comments = [
                    {
                        "id": c.get("id"),
                        "body": c.get("plain_body", c.get("body", "")),
                        "author_id": c.get("author_id"),
                        "public": c.get("public", True),
                        "created_at": c.get("created_at", ""),
                    }
                    for c in c_resp.json().get("comments", [])
                ]
            return {
                "id": t.get("id"),
                "subject": t.get("subject", ""),
                "description": t.get("description", ""),
                "status": t.get("status", ""),
                "priority": t.get("priority", ""),
                "type": t.get("type", ""),
                "requester_id": t.get("requester_id"),
                "assignee_id": t.get("assignee_id"),
                "group_id": t.get("group_id"),
                "tags": t.get("tags", []),
                "created_at": t.get("created_at", ""),
                "updated_at": t.get("updated_at", ""),
                "comments": comments,
            }
        except Exception as exc:
            logger.error("Zendesk get_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def search_zendesk_tickets(query: str, page: int = 1, per_page: int = 25) -> dict:
        """Search Zendesk tickets using Zendesk query syntax.

        Args:
            query: Search query. Supports Zendesk search syntax:
                   'login issue status:open'
                   'type:ticket priority:high assignee:me'
                   'tags:billing created>2024-01-01'
            page: Page number (default 1).
            per_page: Results per page (default 25, max 100).

        Returns:
            dict with matching tickets and total count.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(
                f"{base}/search",
                params={"query": f"type:ticket {query}", "page": page, "per_page": per_page},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            tickets = [
                {
                    "id": t.get("id"),
                    "subject": t.get("subject", ""),
                    "status": t.get("status", ""),
                    "priority": t.get("priority", ""),
                    "created_at": t.get("created_at", ""),
                }
                for t in data.get("results", [])
                if t.get("result_type") == "ticket"
            ]
            return {"tickets": tickets, "count": len(tickets), "total": data.get("count", len(tickets))}
        except Exception as exc:
            logger.error("Zendesk search_tickets error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zendesk_users(role: str = "", page_size: int = 50) -> dict:
        """List Zendesk users (end users and agents).

        Args:
            role: Filter by role — 'end-user', 'agent', 'admin'. Leave blank for all.
            page_size: Number of users to return (default 50).

        Returns:
            dict with list of users (id, name, email, role, active).
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            params: dict = {"page[size]": page_size}
            if role:
                params["role"] = role
            resp = sess.get(f"{base}/users", params=params, timeout=20)
            resp.raise_for_status()
            users = [
                {
                    "id": u.get("id"),
                    "name": u.get("name", ""),
                    "email": u.get("email", ""),
                    "role": u.get("role", ""),
                    "active": u.get("active", True),
                    "created_at": u.get("created_at", ""),
                }
                for u in resp.json().get("users", [])
            ]
            return {"users": users, "count": len(users)}
        except Exception as exc:
            logger.error("Zendesk list_users error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_zendesk_user(user_id: int) -> dict:
        """Get a single Zendesk user by ID.

        Args:
            user_id: Zendesk user ID.

        Returns:
            dict with full user details.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/users/{user_id}", timeout=20)
            resp.raise_for_status()
            return resp.json().get("user", {})
        except Exception as exc:
            logger.error("Zendesk get_user error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zendesk_groups() -> dict:
        """List all agent groups in Zendesk.

        Returns:
            dict with list of groups (id, name, description).
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/groups", timeout=20)
            resp.raise_for_status()
            groups = [
                {"id": g.get("id"), "name": g.get("name", ""), "description": g.get("description", "")}
                for g in resp.json().get("groups", [])
            ]
            return {"groups": groups, "count": len(groups)}
        except Exception as exc:
            logger.error("Zendesk list_groups error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zendesk_macros(page_size: int = 50) -> dict:
        """List Zendesk automation macros available to the current agent.

        Args:
            page_size: Number of macros to return (default 50).

        Returns:
            dict with list of macros (id, title, active).
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/macros", params={"page[size]": page_size}, timeout=20)
            resp.raise_for_status()
            macros = [
                {"id": m.get("id"), "title": m.get("title", ""), "active": m.get("active", True)}
                for m in resp.json().get("macros", [])
            ]
            return {"macros": macros, "count": len(macros)}
        except Exception as exc:
            logger.error("Zendesk list_macros error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_zendesk_ticket(
        subject: str,
        description: str,
        requester_email: str,
        priority: str = "normal",
        ticket_type: str = "question",
        tags: list[str] | None = None,
        assignee_id: int | None = None,
        group_id: int | None = None,
    ) -> dict:
        """Create a new Zendesk support ticket.

        Args:
            subject: Ticket subject.
            description: Initial ticket description.
            requester_email: Email address of the person requesting support.
            priority: 'low', 'normal' (default), 'high', or 'urgent'.
            ticket_type: 'question' (default), 'incident', 'problem', or 'task'.
            tags: List of tag strings to apply. Optional.
            assignee_id: Agent user ID to assign the ticket to. Optional.
            group_id: Group ID to assign the ticket to. Optional.

        Returns:
            dict with created ticket id, subject, and status.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            ticket: dict = {
                "subject": subject,
                "comment": {"body": description},
                "requester": {"email": requester_email},
                "priority": priority,
                "type": ticket_type,
            }
            if tags:
                ticket["tags"] = tags
            if assignee_id is not None:
                ticket["assignee_id"] = assignee_id
            if group_id is not None:
                ticket["group_id"] = group_id
            resp = sess.post(f"{base}/tickets", json={"ticket": ticket}, timeout=20)
            resp.raise_for_status()
            t = resp.json().get("ticket", {})
            return {"id": t.get("id"), "subject": t.get("subject", ""), "status": "created"}
        except Exception as exc:
            logger.error("Zendesk create_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_zendesk_comment(ticket_id: int, body: str, public: bool = True, author_id: int | None = None) -> dict:
        """Add a comment to a Zendesk ticket.

        Args:
            ticket_id: Zendesk ticket ID.
            body: Comment text (plain text or HTML).
            public: True (default) for a public comment visible to the requester.
                    False for an internal private note.
            author_id: Agent user ID for the comment author. Uses the token owner if omitted.

        Returns:
            dict with updated ticket id and comment count.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            comment: dict = {"body": body, "public": public}
            if author_id is not None:
                comment["author_id"] = author_id
            resp = sess.put(f"{base}/tickets/{ticket_id}", json={"ticket": {"comment": comment}}, timeout=20)
            resp.raise_for_status()
            return {"id": ticket_id, "public": public, "status": "commented"}
        except Exception as exc:
            logger.error("Zendesk add_comment error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_zendesk_user(
        name: str,
        email: str,
        role: str = "end-user",
        phone: str = "",
    ) -> dict:
        """Create a new Zendesk user.

        Args:
            name: User full name.
            email: User email address.
            role: 'end-user' (default), 'agent', or 'admin'.
            phone: Phone number. Optional.

        Returns:
            dict with created user id.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            user: dict = {"name": name, "email": email, "role": role}
            if phone:
                user["phone"] = phone
            resp = sess.post(f"{base}/users", json={"user": user}, timeout=20)
            resp.raise_for_status()
            u = resp.json().get("user", {})
            return {"id": u.get("id"), "email": u.get("email", ""), "status": "created"}
        except Exception as exc:
            logger.error("Zendesk create_user error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_zendesk_ticket(ticket_id: int, fields: dict) -> dict:
        """Update fields of a Zendesk ticket.

        Only provided fields are changed; others stay as-is.

        Args:
            ticket_id: Zendesk ticket ID.
            fields: Dict of ticket fields to update. Common fields:
                    status ('new'/'open'/'pending'/'hold'/'solved'/'closed'),
                    priority ('low'/'normal'/'high'/'urgent'),
                    assignee_id (int), group_id (int), tags (list[str]),
                    subject (str), type ('question'/'incident'/'problem'/'task').

        Returns:
            dict with ticket_id and status.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.put(f"{base}/tickets/{ticket_id}", json={"ticket": fields}, timeout=20)
            resp.raise_for_status()
            return {"id": ticket_id, "status": "updated"}
        except Exception as exc:
            logger.error("Zendesk update_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_zendesk_user(user_id: int, fields: dict) -> dict:
        """Update a Zendesk user record.

        Args:
            user_id: Zendesk user ID.
            fields: Dict of user fields to update (name, email, phone,
                    role, external_id, user_fields, etc.).

        Returns:
            dict with user_id and status.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.put(f"{base}/users/{user_id}", json={"user": fields}, timeout=20)
            resp.raise_for_status()
            return {"id": user_id, "status": "updated"}
        except Exception as exc:
            logger.error("Zendesk update_user error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def apply_zendesk_macro(ticket_id: int, macro_id: int) -> dict:
        """Apply a macro to a Zendesk ticket.

        Macros can automatically set fields, add comments, or send notifications.

        Args:
            ticket_id: Zendesk ticket ID.
            macro_id: Macro ID (from list_zendesk_macros).

        Returns:
            dict with the resulting ticket and actions applied.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            preview_resp = sess.get(f"{base}/tickets/{ticket_id}/macros/{macro_id}/apply", timeout=20)
            preview_resp.raise_for_status()
            result = preview_resp.json().get("result", {})
            actions = result.get("actions", [])
            ticket_changes = result.get("ticket", {})
            if ticket_changes:
                apply_resp = sess.put(
                    f"{base}/tickets/{ticket_id}",
                    json={"ticket": ticket_changes},
                    timeout=20,
                )
                apply_resp.raise_for_status()
            return {
                "ticket_id": ticket_id,
                "macro_id": macro_id,
                "actions_applied": [a.get("field", "") for a in actions],
                "status": "applied",
            }
        except Exception as exc:
            logger.error("Zendesk apply_macro error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_zendesk_ticket(ticket_id: int) -> dict:
        """Delete a Zendesk ticket.

        Deleted tickets can be recovered from the Deleted Tickets view within 30 days.

        Args:
            ticket_id: Zendesk ticket ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.delete(f"{base}/tickets/{ticket_id}", timeout=20)
            resp.raise_for_status()
            return {"id": ticket_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Zendesk delete_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_zendesk_user(user_id: int) -> dict:
        """Permanently delete a Zendesk user (GDPR-compliant hard delete).

        WARNING: This permanently removes all user data and cannot be undone.
        The user must have no open tickets before deletion.

        Args:
            user_id: Zendesk user ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("zendesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zendesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.delete(f"{base}/users/{user_id}", timeout=20)
            resp.raise_for_status()
            return {"id": user_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Zendesk delete_user error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_zendesk_tickets,
        get_zendesk_ticket,
        search_zendesk_tickets,
        list_zendesk_users,
        get_zendesk_user,
        list_zendesk_groups,
        list_zendesk_macros,
        # Create
        create_zendesk_ticket,
        add_zendesk_comment,
        create_zendesk_user,
        # Update
        update_zendesk_ticket,
        update_zendesk_user,
        apply_zendesk_macro,
        # Delete
        delete_zendesk_ticket,
        delete_zendesk_user,
    ]
