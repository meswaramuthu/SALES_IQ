"""Zoho Desk tool — Zoho Desk REST API v1.

Required credentials (set in tools_config.json or env vars):
  access_token : Zoho OAuth2 access token with Desk.tickets.ALL scope
  org_id       : Your Zoho Desk organization ID
                 (visible at desk.zoho.com → Settings → Developer Space → API)
  base_url     : Data centre base URL (default https://desk.zoho.com)
                   EU: https://desk.zoho.eu
                   IN: https://desk.zoho.in
                   AU: https://desk.zoho.com.au

In tools_config.json, reference secrets as:
  "access_token": "env:ZOHO_DESK_ACCESS_TOKEN"
  "org_id":       "env:ZOHO_DESK_ORG_ID"

Tools exported:
  READ
    list_zoho_desk_tickets     - list support tickets with optional filters
    get_zoho_desk_ticket       - get a single ticket by ID with comments
    search_zoho_desk_tickets   - search tickets by keyword or field value
    list_zoho_desk_contacts    - list contacts in Zoho Desk
    get_zoho_desk_contact      - get a single contact by ID
    list_zoho_desk_departments - list departments in the org

  CREATE
    create_zoho_desk_ticket    - create a new support ticket
    add_zoho_desk_comment      - add a public or private comment to a ticket
    create_zoho_desk_contact   - create a new contact

  UPDATE
    update_zoho_desk_ticket    - update ticket fields (subject, status, priority...)
    update_zoho_desk_contact   - update a contact record

  DELETE
    delete_zoho_desk_ticket    - delete a ticket
    delete_zoho_desk_contact   - delete a contact
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _session(cfg: dict):
    import requests
    org_id = cfg.get("org_id", "")
    if not org_id:
        raise ValueError("Zoho Desk org_id is required but not configured.")
    sess = requests.Session()
    sess.headers.update({
        "Authorization": f"Zoho-oauthtoken {cfg.get('access_token', '')}",
        "orgId": str(org_id),
    })
    return sess, cfg.get("base_url", "https://desk.zoho.com").rstrip("/") + "/api/v1"


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_zoho_desk_tickets(
        status: str = "",
        priority: str = "",
        department_id: str = "",
        limit: int = 20,
        from_index: int = 0,
    ) -> dict:
        """List Zoho Desk support tickets.

        Args:
            status: Filter by status — 'Open', 'On Hold', 'Escalated', 'Closed'.
                    Leave blank for all statuses.
            priority: Filter by priority — 'Low', 'Medium', 'High', 'Urgent'.
            department_id: Filter by department ID (from list_zoho_desk_departments).
            limit: Max tickets to return (default 20, max 100).
            from_index: Offset for pagination (default 0).

        Returns:
            dict with list of tickets (id, ticketNumber, subject, status, priority, contact).
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            params: dict = {"limit": limit, "from": from_index}
            if status:
                params["status"] = status
            if priority:
                params["priority"] = priority
            if department_id:
                params["departmentId"] = department_id
            resp = sess.get(f"{base}/tickets", params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            tickets = [
                {
                    "id": t.get("id", ""),
                    "ticket_number": t.get("ticketNumber", ""),
                    "subject": t.get("subject", ""),
                    "status": t.get("status", ""),
                    "priority": t.get("priority", ""),
                    "contact": (t.get("contact") or {}).get("firstName", "") + " " + (t.get("contact") or {}).get("lastName", ""),
                    "channel": t.get("channel", ""),
                    "created_time": t.get("createdTime", ""),
                }
                for t in data.get("data", [])
            ]
            return {"tickets": tickets, "count": len(tickets)}
        except Exception as exc:
            logger.error("Zoho Desk list_tickets error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_zoho_desk_ticket(ticket_id: str) -> dict:
        """Get a single Zoho Desk ticket with its thread/comments.

        Args:
            ticket_id: Zoho Desk ticket ID.

        Returns:
            dict with full ticket details and comment thread.
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/tickets/{ticket_id}", params={"include": "contacts,assignee,departments,team"}, timeout=20)
            resp.raise_for_status()
            t = resp.json()
            # Fetch thread
            thread_resp = sess.get(f"{base}/tickets/{ticket_id}/comments", timeout=20)
            comments = []
            if thread_resp.ok:
                for c in thread_resp.json().get("data", []):
                    comments.append({
                        "id": c.get("id", ""),
                        "content": c.get("content", ""),
                        "type": c.get("type", ""),
                        "author": c.get("author", {}).get("name", ""),
                        "created_time": c.get("createdTime", ""),
                    })
            return {
                "id": t.get("id", ""),
                "ticket_number": t.get("ticketNumber", ""),
                "subject": t.get("subject", ""),
                "description": t.get("description", ""),
                "status": t.get("status", ""),
                "priority": t.get("priority", ""),
                "assignee": (t.get("assignee") or {}).get("firstName", ""),
                "contact": t.get("contact", {}),
                "channel": t.get("channel", ""),
                "created_time": t.get("createdTime", ""),
                "due_date": t.get("dueDate", ""),
                "comments": comments,
            }
        except Exception as exc:
            logger.error("Zoho Desk get_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def search_zoho_desk_tickets(query: str, limit: int = 20) -> dict:
        """Search Zoho Desk tickets by keyword.

        Args:
            query: Search keyword (matches subject, description, ticket number).
            limit: Max results to return (default 20).

        Returns:
            dict with list of matching tickets.
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(
                f"{base}/tickets/search",
                params={"query": query, "limit": limit},
                timeout=20,
            )
            resp.raise_for_status()
            tickets = [
                {
                    "id": t.get("id", ""),
                    "ticket_number": t.get("ticketNumber", ""),
                    "subject": t.get("subject", ""),
                    "status": t.get("status", ""),
                    "priority": t.get("priority", ""),
                }
                for t in resp.json().get("data", [])
            ]
            return {"tickets": tickets, "count": len(tickets)}
        except Exception as exc:
            logger.error("Zoho Desk search_tickets error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zoho_desk_contacts(limit: int = 20, from_index: int = 0) -> dict:
        """List contacts registered in Zoho Desk.

        Args:
            limit: Max contacts to return (default 20, max 100).
            from_index: Offset for pagination.

        Returns:
            dict with list of contacts (id, firstName, lastName, email, phone).
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/contacts", params={"limit": limit, "from": from_index}, timeout=20)
            resp.raise_for_status()
            contacts = [
                {
                    "id": c.get("id", ""),
                    "first_name": c.get("firstName", ""),
                    "last_name": c.get("lastName", ""),
                    "email": c.get("email", ""),
                    "phone": c.get("phone", ""),
                    "account_name": c.get("accountName", ""),
                }
                for c in resp.json().get("data", [])
            ]
            return {"contacts": contacts, "count": len(contacts)}
        except Exception as exc:
            logger.error("Zoho Desk list_contacts error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_zoho_desk_contact(contact_id: str) -> dict:
        """Get a single Zoho Desk contact by ID.

        Args:
            contact_id: Zoho Desk contact ID.

        Returns:
            dict with full contact details.
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/contacts/{contact_id}", timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Zoho Desk get_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zoho_desk_departments() -> dict:
        """List all departments in the Zoho Desk org.

        Returns:
            dict with list of departments (id, name, description, isEnabled).
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/departments", timeout=20)
            resp.raise_for_status()
            depts = [
                {
                    "id": d.get("id", ""),
                    "name": d.get("name", ""),
                    "description": d.get("description", ""),
                    "is_enabled": d.get("isEnabled", True),
                }
                for d in resp.json().get("data", [])
            ]
            return {"departments": depts, "count": len(depts)}
        except Exception as exc:
            logger.error("Zoho Desk list_departments error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_zoho_desk_ticket(
        subject: str,
        department_id: str,
        contact_id: str = "",
        email: str = "",
        description: str = "",
        priority: str = "Medium",
        status: str = "Open",
        channel: str = "Email",
    ) -> dict:
        """Create a new support ticket in Zoho Desk.

        Args:
            subject: Ticket subject line.
            department_id: ID of the department to assign (from list_zoho_desk_departments).
            contact_id: ID of an existing contact. If provided, email is ignored.
            email: Email address of the requester (used when no contact_id given).
            description: Ticket body/description.
            priority: 'Low', 'Medium' (default), 'High', or 'Urgent'.
            status: Initial status — 'Open' (default), 'On Hold'.
            channel: Source channel — 'Email' (default), 'Phone', 'Chat', 'Twitter', etc.

        Returns:
            dict with created ticket id, ticketNumber, and status.
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {
                "subject": subject,
                "departmentId": department_id,
                "priority": priority,
                "status": status,
                "channel": channel,
            }
            if description:
                payload["description"] = description
            if contact_id:
                payload["contactId"] = contact_id
            elif email:
                payload["email"] = email
            resp = sess.post(f"{base}/tickets", json=payload, timeout=20)
            resp.raise_for_status()
            t = resp.json()
            return {
                "id": t.get("id", ""),
                "ticket_number": t.get("ticketNumber", ""),
                "subject": t.get("subject", ""),
                "status": "created",
            }
        except Exception as exc:
            logger.error("Zoho Desk create_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_zoho_desk_comment(ticket_id: str, content: str, is_public: bool = True) -> dict:
        """Add a comment/reply to a Zoho Desk ticket.

        Args:
            ticket_id: Zoho Desk ticket ID.
            content: Comment body text.
            is_public: True (default) to send as a public reply visible to the customer.
                       False for an internal private note.

        Returns:
            dict with comment id and created time.
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload = {"content": content, "isPublic": is_public}
            resp = sess.post(f"{base}/tickets/{ticket_id}/comments", json=payload, timeout=20)
            resp.raise_for_status()
            c = resp.json()
            return {
                "id": c.get("id", ""),
                "created_time": c.get("createdTime", ""),
                "is_public": c.get("isPublic", is_public),
                "status": "commented",
            }
        except Exception as exc:
            logger.error("Zoho Desk add_comment error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_zoho_desk_contact(
        first_name: str,
        last_name: str,
        email: str,
        phone: str = "",
        account_name: str = "",
        description: str = "",
    ) -> dict:
        """Create a new contact in Zoho Desk.

        Args:
            first_name: Contact first name.
            last_name: Contact last name.
            email: Contact email address.
            phone: Phone number. Optional.
            account_name: Company/account name. Optional.
            description: Additional notes. Optional.

        Returns:
            dict with created contact id.
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {"firstName": first_name, "lastName": last_name, "email": email}
            if phone:
                payload["phone"] = phone
            if account_name:
                payload["accountName"] = account_name
            if description:
                payload["description"] = description
            resp = sess.post(f"{base}/contacts", json=payload, timeout=20)
            resp.raise_for_status()
            c = resp.json()
            return {"id": c.get("id", ""), "email": c.get("email", ""), "status": "created"}
        except Exception as exc:
            logger.error("Zoho Desk create_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_zoho_desk_ticket(ticket_id: str, fields: dict) -> dict:
        """Update fields of an existing Zoho Desk ticket.

        Args:
            ticket_id: Zoho Desk ticket ID.
            fields: Dict of fields to update. Common fields:
                    subject, description, status, priority, departmentId,
                    assigneeId, dueDate, customFields.

        Returns:
            dict with ticket id and updated status.
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.patch(f"{base}/tickets/{ticket_id}", json=fields, timeout=20)
            resp.raise_for_status()
            t = resp.json()
            return {"id": t.get("id", ticket_id), "status": "updated"}
        except Exception as exc:
            logger.error("Zoho Desk update_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_zoho_desk_contact(contact_id: str, fields: dict) -> dict:
        """Update a Zoho Desk contact record.

        Args:
            contact_id: Zoho Desk contact ID.
            fields: Dict of fields to update (firstName, lastName, email, phone, etc.).

        Returns:
            dict with contact id and status.
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.patch(f"{base}/contacts/{contact_id}", json=fields, timeout=20)
            resp.raise_for_status()
            return {"id": contact_id, "status": "updated"}
        except Exception as exc:
            logger.error("Zoho Desk update_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_zoho_desk_ticket(ticket_id: str) -> dict:
        """Delete a Zoho Desk ticket.

        Args:
            ticket_id: Zoho Desk ticket ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.delete(f"{base}/tickets/{ticket_id}", timeout=20)
            resp.raise_for_status()
            return {"id": ticket_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Zoho Desk delete_ticket error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_zoho_desk_contact(contact_id: str) -> dict:
        """Delete a Zoho Desk contact.

        Args:
            contact_id: Zoho Desk contact ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("zoho_desk")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Desk tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.delete(f"{base}/contacts/{contact_id}", timeout=20)
            resp.raise_for_status()
            return {"id": contact_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Zoho Desk delete_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_zoho_desk_tickets,
        get_zoho_desk_ticket,
        search_zoho_desk_tickets,
        list_zoho_desk_contacts,
        get_zoho_desk_contact,
        list_zoho_desk_departments,
        # Create
        create_zoho_desk_ticket,
        add_zoho_desk_comment,
        create_zoho_desk_contact,
        # Update
        update_zoho_desk_ticket,
        update_zoho_desk_contact,
        # Delete
        delete_zoho_desk_ticket,
        delete_zoho_desk_contact,
    ]
