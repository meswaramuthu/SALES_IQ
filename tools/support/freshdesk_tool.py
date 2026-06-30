"""FreshDesk tool — Freshdesk REST API v2.

Required credentials (set in tools_config.json or env vars):
  api_key : Freshdesk API key (My Profile → API Key in Freshdesk)
  domain  : Your Freshdesk subdomain (e.g. 'mycompany' for mycompany.freshdesk.com)

In tools_config.json, reference secrets as:
  "api_key": "env:FRESHDESK_API_KEY"
  "domain":  "env:FRESHDESK_DOMAIN"

Tools exported:
  READ
    list_freshdesk_tickets    - list tickets with optional status/priority filter
    get_freshdesk_ticket      - get a single ticket with conversations
    search_freshdesk_tickets  - search tickets by keyword or custom query
    list_freshdesk_contacts   - list contacts
    get_freshdesk_contact     - get a single contact by ID
    list_freshdesk_agents     - list support agents

  CREATE
    create_freshdesk_ticket   - create a new support ticket
    add_freshdesk_reply       - add a public reply to a ticket
    add_freshdesk_note        - add a private note to a ticket
    create_freshdesk_contact  - create a new contact

  UPDATE
    update_freshdesk_ticket   - update ticket fields (status, priority, assignee...)
    update_freshdesk_contact  - update a contact record

  DELETE
    delete_freshdesk_ticket   - permanently delete a ticket
    delete_freshdesk_contact  - permanently delete a contact
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)

_STATUS_MAP = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed", 6: "Waiting on Customer", 7: "Waiting on Third Party"}
_PRIORITY_MAP = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}


def _session(cfg: dict):
    import requests
    api_key = cfg.get("api_key", "")
    domain = cfg.get("domain", "").rstrip("/")
    if not domain.startswith("http"):
        domain = f"https://{domain}.freshdesk.com"
    sess = requests.Session()
    sess.auth = (api_key, "X")
    sess.headers.update({"Content-Type": "application/json"})
    return sess, f"{domain}/api/v2"


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_freshdesk_tickets(
        status: str = "",
        priority: str = "",
        requester_email: str = "",
        page: int = 1,
        per_page: int = 30,
    ) -> dict:
        """List Freshdesk support tickets.

        Args:
            status: Filter by status — 'open', 'pending', 'resolved', 'closed'.
                    Leave blank for all open tickets.
            priority: Filter by priority — 'low', 'medium', 'high', 'urgent'.
            requester_email: Filter tickets by requester email.
            page: Page number for pagination (default 1).
            per_page: Tickets per page (default 30, max 100).

        Returns:
            dict with list of tickets (id, subject, status, priority, requester, assignee).
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            status_codes = {"open": 2, "pending": 3, "resolved": 4, "closed": 5}
            priority_codes = {"low": 1, "medium": 2, "high": 3, "urgent": 4}
            params: dict = {"page": page, "per_page": per_page, "include": "requester,assignee"}
            if status and status.lower() in status_codes:
                params["status"] = status_codes[status.lower()]
            if priority and priority.lower() in priority_codes:
                params["priority"] = priority_codes[priority.lower()]
            if requester_email:
                params["email"] = requester_email
            resp = sess.get(f"{base}/tickets", params=params, timeout=20)
            resp.raise_for_status()
            tickets = [
                {
                    "id": t.get("id"),
                    "subject": t.get("subject", ""),
                    "status": _STATUS_MAP.get(t.get("status", 2), str(t.get("status", ""))),
                    "priority": _PRIORITY_MAP.get(t.get("priority", 2), str(t.get("priority", ""))),
                    "requester_email": t.get("requester", {}).get("email", t.get("email", "")),
                    "assignee": (t.get("assignee") or {}).get("name", "Unassigned"),
                    "created_at": t.get("created_at", ""),
                    "updated_at": t.get("updated_at", ""),
                    "tags": t.get("tags", []),
                }
                for t in resp.json()
            ]
            return {"tickets": tickets, "count": len(tickets), "page": page}
        except Exception as exc:
            logger.error("FreshDesk list_tickets error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_freshdesk_ticket(ticket_id: int) -> dict:
        """Get a single Freshdesk ticket with full details and conversations.

        Args:
            ticket_id: Freshdesk ticket ID (numeric).

        Returns:
            dict with ticket details, description, and all conversation replies/notes.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(
                f"{base}/tickets/{ticket_id}",
                params={"include": "conversations,requester,assignee,company"},
                timeout=20,
            )
            resp.raise_for_status()
            t = resp.json()
            conversations = [
                {
                    "id": c.get("id"),
                    "body_text": c.get("body_text", ""),
                    "from_email": c.get("from_email", ""),
                    "private": c.get("private", False),
                    "created_at": c.get("created_at", ""),
                }
                for c in t.get("conversations", [])
            ]
            return {
                "id": t.get("id"),
                "subject": t.get("subject", ""),
                "description_text": t.get("description_text", ""),
                "status": _STATUS_MAP.get(t.get("status", 2), str(t.get("status", ""))),
                "priority": _PRIORITY_MAP.get(t.get("priority", 2), str(t.get("priority", ""))),
                "requester_email": t.get("requester", {}).get("email", ""),
                "requester_name": t.get("requester", {}).get("name", ""),
                "assignee": (t.get("assignee") or {}).get("name", "Unassigned"),
                "tags": t.get("tags", []),
                "created_at": t.get("created_at", ""),
                "conversations": conversations,
            }
        except Exception as exc:
            logger.error("FreshDesk get_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def search_freshdesk_tickets(query: str, page: int = 1) -> dict:
        """Search Freshdesk tickets using a keyword or query expression.

        Args:
            query: Search term or Freshdesk query expression.
                   Examples: 'login issue', 'priority:urgent status:open',
                   'subject:"payment failed" AND requester_id:12345'
            page: Page number (default 1, max 10 pages = 300 results).

        Returns:
            dict with list of matching tickets.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(
                f"{base}/search/tickets",
                params={"query": query, "page": page},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            tickets = [
                {
                    "id": t.get("id"),
                    "subject": t.get("subject", ""),
                    "status": _STATUS_MAP.get(t.get("status", 2), ""),
                    "priority": _PRIORITY_MAP.get(t.get("priority", 2), ""),
                    "requester_email": t.get("email", ""),
                    "created_at": t.get("created_at", ""),
                }
                for t in data.get("results", [])
            ]
            return {"tickets": tickets, "count": len(tickets), "total": data.get("total", len(tickets))}
        except Exception as exc:
            logger.error("FreshDesk search_tickets error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_freshdesk_contacts(
        email: str = "",
        page: int = 1,
        per_page: int = 30,
    ) -> dict:
        """List Freshdesk contacts.

        Args:
            email: Filter by exact email address.
            page: Page number (default 1).
            per_page: Contacts per page (default 30, max 100).

        Returns:
            dict with list of contacts (id, name, email, phone, company).
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            params: dict = {"page": page, "per_page": per_page}
            if email:
                params["email"] = email
            resp = sess.get(f"{base}/contacts", params=params, timeout=20)
            resp.raise_for_status()
            contacts = [
                {
                    "id": c.get("id"),
                    "name": c.get("name", ""),
                    "email": c.get("email", ""),
                    "phone": c.get("phone", ""),
                    "company_id": c.get("company_id"),
                    "active": c.get("active", True),
                }
                for c in resp.json()
            ]
            return {"contacts": contacts, "count": len(contacts)}
        except Exception as exc:
            logger.error("FreshDesk list_contacts error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_freshdesk_contact(contact_id: int) -> dict:
        """Get a single Freshdesk contact by ID.

        Args:
            contact_id: Freshdesk contact ID.

        Returns:
            dict with full contact details.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/contacts/{contact_id}", timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("FreshDesk get_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_freshdesk_agents(page: int = 1, per_page: int = 50) -> dict:
        """List Freshdesk support agents.

        Args:
            page: Page number (default 1).
            per_page: Agents per page (default 50).

        Returns:
            dict with list of agents (id, name, email, type, available).
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/agents", params={"page": page, "per_page": per_page}, timeout=20)
            resp.raise_for_status()
            agents = [
                {
                    "id": a.get("id"),
                    "name": a.get("contact", {}).get("name", ""),
                    "email": a.get("contact", {}).get("email", ""),
                    "type": a.get("type", ""),
                    "available": a.get("available", True),
                }
                for a in resp.json()
            ]
            return {"agents": agents, "count": len(agents)}
        except Exception as exc:
            logger.error("FreshDesk list_agents error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_freshdesk_ticket(
        subject: str,
        description: str,
        email: str,
        priority: str = "Medium",
        status: str = "Open",
        tags: list[str] | None = None,
        group_id: int | None = None,
        agent_id: int | None = None,
    ) -> dict:
        """Create a new Freshdesk support ticket.

        Args:
            subject: Ticket subject line.
            description: Ticket description/body (HTML supported).
            email: Requester's email address.
            priority: 'Low', 'Medium' (default), 'High', or 'Urgent'.
            status: 'Open' (default), 'Pending', 'Resolved', 'Closed'.
            tags: Optional list of tag strings.
            group_id: ID of the agent group to assign. Optional.
            agent_id: ID of the agent to assign. Optional.

        Returns:
            dict with created ticket id and subject.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            priority_codes = {"low": 1, "medium": 2, "high": 3, "urgent": 4}
            status_codes = {"open": 2, "pending": 3, "resolved": 4, "closed": 5}
            sess, base = _session(cfg.config)
            payload: dict = {
                "subject": subject,
                "description": description,
                "email": email,
                "priority": priority_codes.get(priority.lower(), 2),
                "status": status_codes.get(status.lower(), 2),
            }
            if tags:
                payload["tags"] = tags
            if group_id is not None:
                payload["group_id"] = group_id
            if agent_id is not None:
                payload["responder_id"] = agent_id
            resp = sess.post(f"{base}/tickets", json=payload, timeout=20)
            resp.raise_for_status()
            t = resp.json()
            return {"id": t.get("id"), "subject": t.get("subject", ""), "status": "created"}
        except Exception as exc:
            logger.error("FreshDesk create_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_freshdesk_reply(ticket_id: int, body: str, from_email: str = "") -> dict:
        """Add a public reply to a Freshdesk ticket (sent to the requester).

        Args:
            ticket_id: Freshdesk ticket ID.
            body: Reply body text (HTML supported).
            from_email: Agent/group email to send from. Uses default if blank.

        Returns:
            dict with reply id and status.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {"body": body}
            if from_email:
                payload["from_email"] = from_email
            resp = sess.post(f"{base}/tickets/{ticket_id}/reply", json=payload, timeout=20)
            resp.raise_for_status()
            c = resp.json()
            return {"id": c.get("id"), "created_at": c.get("created_at", ""), "status": "replied"}
        except Exception as exc:
            logger.error("FreshDesk add_reply error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_freshdesk_note(ticket_id: int, body: str, private: bool = True) -> dict:
        """Add a note to a Freshdesk ticket.

        Args:
            ticket_id: Freshdesk ticket ID.
            body: Note body text.
            private: True (default) for a private internal note. False for a public note.

        Returns:
            dict with note id and status.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.post(
                f"{base}/tickets/{ticket_id}/notes",
                json={"body": body, "private": private},
                timeout=20,
            )
            resp.raise_for_status()
            c = resp.json()
            return {"id": c.get("id"), "private": private, "status": "noted"}
        except Exception as exc:
            logger.error("FreshDesk add_note error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_freshdesk_contact(
        name: str,
        email: str,
        phone: str = "",
        company_id: int | None = None,
        description: str = "",
    ) -> dict:
        """Create a new Freshdesk contact.

        Args:
            name: Contact full name.
            email: Primary email address.
            phone: Phone number. Optional.
            company_id: Associated Freshdesk company ID. Optional.
            description: Notes about the contact. Optional.

        Returns:
            dict with created contact id.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {"name": name, "email": email}
            if phone:
                payload["phone"] = phone
            if company_id is not None:
                payload["company_id"] = company_id
            if description:
                payload["description"] = description
            resp = sess.post(f"{base}/contacts", json=payload, timeout=20)
            resp.raise_for_status()
            c = resp.json()
            return {"id": c.get("id"), "email": c.get("email", ""), "status": "created"}
        except Exception as exc:
            logger.error("FreshDesk create_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_freshdesk_ticket(ticket_id: int, fields: dict) -> dict:
        """Update fields of a Freshdesk ticket.

        Only the provided fields are changed; others stay as-is.

        Args:
            ticket_id: Freshdesk ticket ID.
            fields: Dict of fields to update. Common fields:
                    subject, description, status (2-5 integer or string),
                    priority (1-4 integer or string), responder_id (agent ID),
                    group_id, tags (list), due_by (ISO datetime string).
                    Use status strings: 'open'/'pending'/'resolved'/'closed'.
                    Use priority strings: 'low'/'medium'/'high'/'urgent'.

        Returns:
            dict with ticket_id and status.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            status_codes = {"open": 2, "pending": 3, "resolved": 4, "closed": 5}
            priority_codes = {"low": 1, "medium": 2, "high": 3, "urgent": 4}
            fields = dict(fields)
            if "status" in fields and isinstance(fields["status"], str):
                fields["status"] = status_codes.get(fields["status"].lower(), fields["status"])
            if "priority" in fields and isinstance(fields["priority"], str):
                fields["priority"] = priority_codes.get(fields["priority"].lower(), fields["priority"])
            resp = sess.put(f"{base}/tickets/{ticket_id}", json=fields, timeout=20)
            resp.raise_for_status()
            return {"id": ticket_id, "status": "updated"}
        except Exception as exc:
            logger.error("FreshDesk update_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_freshdesk_contact(contact_id: int, fields: dict) -> dict:
        """Update a Freshdesk contact record.

        Args:
            contact_id: Freshdesk contact ID.
            fields: Dict of fields to update (name, email, phone, company_id,
                    description, custom_fields, etc.).

        Returns:
            dict with contact_id and status.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.put(f"{base}/contacts/{contact_id}", json=fields, timeout=20)
            resp.raise_for_status()
            return {"id": contact_id, "status": "updated"}
        except Exception as exc:
            logger.error("FreshDesk update_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_freshdesk_ticket(ticket_id: int) -> dict:
        """Permanently delete a Freshdesk ticket.

        WARNING: This is irreversible. All ticket data and conversations
        will be permanently removed.

        Args:
            ticket_id: Freshdesk ticket ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.delete(f"{base}/tickets/{ticket_id}", timeout=20)
            resp.raise_for_status()
            return {"id": ticket_id, "status": "deleted"}
        except Exception as exc:
            logger.error("FreshDesk delete_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_freshdesk_contact(contact_id: int) -> dict:
        """Permanently delete a Freshdesk contact.

        Args:
            contact_id: Freshdesk contact ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("freshdesk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "FreshDesk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.delete(f"{base}/contacts/{contact_id}", timeout=20)
            resp.raise_for_status()
            return {"id": contact_id, "status": "deleted"}
        except Exception as exc:
            logger.error("FreshDesk delete_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_freshdesk_tickets,
        get_freshdesk_ticket,
        search_freshdesk_tickets,
        list_freshdesk_contacts,
        get_freshdesk_contact,
        list_freshdesk_agents,
        # Create
        create_freshdesk_ticket,
        add_freshdesk_reply,
        add_freshdesk_note,
        create_freshdesk_contact,
        # Update
        update_freshdesk_ticket,
        update_freshdesk_contact,
        # Delete
        delete_freshdesk_ticket,
        delete_freshdesk_contact,
    ]
