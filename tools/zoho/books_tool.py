"""Zoho Books tool — Zoho Books REST API v3.

Required credentials (set in tools_config.json):
  client_id       : Zoho OAuth2 client ID
  client_secret   : Zoho OAuth2 client secret
  refresh_token   : Zoho OAuth2 refresh token (permanent — never needs rotation)
  organization_id : Zoho Books organization ID
                    (Settings → Organization Profile → Organization ID)
  base_url        : Data centre base URL (default https://www.zohoapis.com)
                      EU: https://www.zohoapis.eu
                      IN: https://www.zohoapis.in
  accounts_url    : (optional) Zoho accounts domain for token refresh

In tools_config.json, reference secrets as:
  "client_id":       "env:ZOHO_CLIENT_ID"
  "client_secret":   "env:ZOHO_CLIENT_SECRET"
  "refresh_token":   "env:ZOHO_REFRESH_TOKEN"
  "organization_id": "env:ZOHO_BOOKS_ORG_ID"

The access token is fetched and cached automatically; it never needs to be
stored or rotated manually.

Tools exported:
  READ
    list_zoho_books_invoices    - list invoices with optional status filter
    get_zoho_books_invoice      - get a single invoice by ID
    list_zoho_books_contacts    - list customers/vendors
    get_zoho_books_contact      - get a single contact by ID
    list_zoho_books_expenses    - list expenses
    get_zoho_books_expense      - get a single expense by ID
    list_zoho_books_items       - list products/services items

  CREATE
    create_zoho_books_invoice   - create a new invoice
    create_zoho_books_contact   - create a new customer or vendor
    create_zoho_books_expense   - record a new expense

  UPDATE
    update_zoho_books_invoice   - update invoice fields
    update_zoho_books_contact   - update a contact record
    mark_zoho_books_invoice_sent - mark an invoice as sent

  DELETE
    delete_zoho_books_invoice   - delete an invoice (only draft/void invoices)
    delete_zoho_books_contact   - delete a contact
    delete_zoho_books_expense   - delete an expense record
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _session(cfg: dict):
    import requests
    from tools.zoho.auth import get_zoho_access_token
    token = get_zoho_access_token(cfg)
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Zoho-oauthtoken {token}"})
    org_id = str(cfg.get("organization_id", ""))
    base = cfg.get("base_url", "https://www.zohoapis.com").rstrip("/") + "/books/v3"
    return sess, base, org_id


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_zoho_books_invoices(status: str = "", page: int = 1, per_page: int = 25) -> dict:
        """List invoices in Zoho Books.

        Args:
            status: Filter by status — 'draft', 'sent', 'overdue', 'paid',
                    'partially_paid', 'void'. Leave blank for all.
            page: Page number (default 1).
            per_page: Records per page (default 25, max 200).

        Returns:
            dict with list of invoices (id, invoice_number, customer, total, status, date).
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            params: dict = {"organization_id": org_id, "page": page, "per_page": per_page}
            if status:
                params["status"] = status
            resp = sess.get(f"{base}/invoices", params=params, timeout=20)
            resp.raise_for_status()
            invoices = [
                {
                    "id": inv.get("invoice_id", ""),
                    "invoice_number": inv.get("invoice_number", ""),
                    "customer": inv.get("customer_name", ""),
                    "date": inv.get("date", ""),
                    "due_date": inv.get("due_date", ""),
                    "total": inv.get("total", 0),
                    "balance": inv.get("balance", 0),
                    "status": inv.get("status", ""),
                    "currency": inv.get("currency_code", ""),
                }
                for inv in resp.json().get("invoices", [])
            ]
            return {"invoices": invoices, "count": len(invoices), "page": page}
        except Exception as exc:
            logger.error("Zoho Books list_invoices error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_zoho_books_invoice(invoice_id: str) -> dict:
        """Get a single Zoho Books invoice by ID.

        Args:
            invoice_id: Zoho Books invoice ID.

        Returns:
            dict with full invoice details including line items and payment history.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            resp = sess.get(f"{base}/invoices/{invoice_id}", params={"organization_id": org_id}, timeout=20)
            resp.raise_for_status()
            inv = resp.json().get("invoice", {})
            return {
                "id": inv.get("invoice_id", ""),
                "invoice_number": inv.get("invoice_number", ""),
                "customer": inv.get("customer_name", ""),
                "customer_id": inv.get("customer_id", ""),
                "date": inv.get("date", ""),
                "due_date": inv.get("due_date", ""),
                "status": inv.get("status", ""),
                "total": inv.get("total", 0),
                "balance": inv.get("balance", 0),
                "currency": inv.get("currency_code", ""),
                "line_items": inv.get("line_items", []),
                "notes": inv.get("notes", ""),
                "terms": inv.get("terms", ""),
                "payment_made": inv.get("payment_made", 0),
            }
        except Exception as exc:
            logger.error("Zoho Books get_invoice error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zoho_books_contacts(
        contact_type: str = "",
        search_text: str = "",
        page: int = 1,
        per_page: int = 25,
    ) -> dict:
        """List customers and vendors in Zoho Books.

        Args:
            contact_type: 'customer', 'vendor', or blank for all.
            search_text: Search by name or email fragment.
            page: Page number (default 1).
            per_page: Records per page (default 25, max 200).

        Returns:
            dict with list of contacts (id, name, email, phone, type, outstanding).
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            params: dict = {"organization_id": org_id, "page": page, "per_page": per_page}
            if contact_type:
                params["contact_type"] = contact_type
            if search_text:
                params["search_text"] = search_text
            resp = sess.get(f"{base}/contacts", params=params, timeout=20)
            resp.raise_for_status()
            contacts = [
                {
                    "id": c.get("contact_id", ""),
                    "name": c.get("contact_name", ""),
                    "type": c.get("contact_type", ""),
                    "email": c.get("email", ""),
                    "phone": c.get("phone", ""),
                    "outstanding": c.get("outstanding_receivable_amount", 0),
                    "currency": c.get("currency_code", ""),
                }
                for c in resp.json().get("contacts", [])
            ]
            return {"contacts": contacts, "count": len(contacts)}
        except Exception as exc:
            logger.error("Zoho Books list_contacts error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_zoho_books_contact(contact_id: str) -> dict:
        """Get a single Zoho Books contact (customer or vendor) by ID.

        Args:
            contact_id: Zoho Books contact ID.

        Returns:
            dict with full contact details.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            resp = sess.get(f"{base}/contacts/{contact_id}", params={"organization_id": org_id}, timeout=20)
            resp.raise_for_status()
            return resp.json().get("contact", {})
        except Exception as exc:
            logger.error("Zoho Books get_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zoho_books_expenses(
        status: str = "",
        page: int = 1,
        per_page: int = 25,
    ) -> dict:
        """List expense records in Zoho Books.

        Args:
            status: Filter by status — 'unbilled', 'invoiced'. Leave blank for all.
            page: Page number (default 1).
            per_page: Records per page (default 25).

        Returns:
            dict with list of expenses (id, date, amount, account, status).
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            params: dict = {"organization_id": org_id, "page": page, "per_page": per_page}
            if status:
                params["status"] = status
            resp = sess.get(f"{base}/expenses", params=params, timeout=20)
            resp.raise_for_status()
            expenses = [
                {
                    "id": e.get("expense_id", ""),
                    "date": e.get("date", ""),
                    "total": e.get("total", 0),
                    "account": e.get("account_name", ""),
                    "vendor": e.get("vendor_name", ""),
                    "description": e.get("description", ""),
                    "status": e.get("status", ""),
                    "currency": e.get("currency_code", ""),
                }
                for e in resp.json().get("expenses", [])
            ]
            return {"expenses": expenses, "count": len(expenses)}
        except Exception as exc:
            logger.error("Zoho Books list_expenses error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_zoho_books_expense(expense_id: str) -> dict:
        """Get a single Zoho Books expense by ID.

        Args:
            expense_id: Zoho Books expense ID.

        Returns:
            dict with full expense details.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            resp = sess.get(f"{base}/expenses/{expense_id}", params={"organization_id": org_id}, timeout=20)
            resp.raise_for_status()
            return resp.json().get("expense", {})
        except Exception as exc:
            logger.error("Zoho Books get_expense error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zoho_books_items(search_text: str = "", page: int = 1, per_page: int = 25) -> dict:
        """List products/service items in Zoho Books.

        Args:
            search_text: Filter by item name fragment.
            page: Page number (default 1).
            per_page: Records per page (default 25).

        Returns:
            dict with list of items (id, name, rate, type, unit, account).
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            params: dict = {"organization_id": org_id, "page": page, "per_page": per_page}
            if search_text:
                params["search_text"] = search_text
            resp = sess.get(f"{base}/items", params=params, timeout=20)
            resp.raise_for_status()
            items = [
                {
                    "id": it.get("item_id", ""),
                    "name": it.get("name", ""),
                    "rate": it.get("rate", 0),
                    "type": it.get("item_type", ""),
                    "unit": it.get("unit", ""),
                    "account": it.get("account_name", ""),
                    "status": it.get("status", ""),
                }
                for it in resp.json().get("items", [])
            ]
            return {"items": items, "count": len(items)}
        except Exception as exc:
            logger.error("Zoho Books list_items error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_zoho_books_invoice(
        customer_id: str,
        line_items: list[dict],
        date: str = "",
        due_date: str = "",
        notes: str = "",
        terms: str = "",
    ) -> dict:
        """Create a new invoice in Zoho Books.

        Args:
            customer_id: Zoho Books contact ID of the customer (from list_zoho_books_contacts).
            line_items: List of line item dicts. Each dict must have:
                        - 'item_id' (str): Product/service item ID, OR
                        - 'name' (str): Custom item name
                        - 'rate' (float): Unit price
                        - 'quantity' (int): Quantity (default 1)
                        - 'description' (str, optional): Line description
            date: Invoice date in YYYY-MM-DD format. Defaults to today.
            due_date: Payment due date in YYYY-MM-DD format.
            notes: Notes to customer (visible on invoice).
            terms: Payment terms (visible on invoice).

        Returns:
            dict with created invoice_id, invoice_number, total, and status.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            payload: dict = {
                "customer_id": customer_id,
                "line_items": line_items,
            }
            if date:
                payload["date"] = date
            if due_date:
                payload["due_date"] = due_date
            if notes:
                payload["notes"] = notes
            if terms:
                payload["terms"] = terms
            resp = sess.post(f"{base}/invoices", params={"organization_id": org_id}, json=payload, timeout=20)
            resp.raise_for_status()
            inv = resp.json().get("invoice", {})
            return {
                "id": inv.get("invoice_id", ""),
                "invoice_number": inv.get("invoice_number", ""),
                "total": inv.get("total", 0),
                "status": "created",
            }
        except Exception as exc:
            logger.error("Zoho Books create_invoice error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_zoho_books_contact(
        name: str,
        contact_type: str = "customer",
        email: str = "",
        phone: str = "",
        company_name: str = "",
        billing_address: dict | None = None,
    ) -> dict:
        """Create a new customer or vendor in Zoho Books.

        Args:
            name: Contact display name.
            contact_type: 'customer' (default) or 'vendor'.
            email: Primary email address.
            phone: Phone number.
            company_name: Company/organization name.
            billing_address: Optional dict with keys: address, city, state, zip, country.

        Returns:
            dict with created contact_id.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            payload: dict = {"contact_name": name, "contact_type": contact_type}
            if email:
                payload["email"] = email
            if phone:
                payload["phone"] = phone
            if company_name:
                payload["company_name"] = company_name
            if billing_address:
                payload["billing_address"] = billing_address
            resp = sess.post(f"{base}/contacts", params={"organization_id": org_id}, json=payload, timeout=20)
            resp.raise_for_status()
            c = resp.json().get("contact", {})
            return {
                "id": c.get("contact_id", ""),
                "name": c.get("contact_name", ""),
                "type": c.get("contact_type", ""),
                "status": "created",
            }
        except Exception as exc:
            logger.error("Zoho Books create_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_zoho_books_expense(
        account_id: str,
        date: str,
        amount: float,
        description: str = "",
        vendor_id: str = "",
        currency_code: str = "USD",
    ) -> dict:
        """Record a new expense in Zoho Books.

        Args:
            account_id: Expense account ID (e.g. Office Supplies, Travel).
            date: Expense date in YYYY-MM-DD format.
            amount: Total expense amount.
            description: Description of the expense.
            vendor_id: Optional vendor contact ID.
            currency_code: Currency code (default 'USD').

        Returns:
            dict with created expense_id and total.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            payload: dict = {
                "account_id": account_id,
                "date": date,
                "amount": amount,
                "currency_code": currency_code,
            }
            if description:
                payload["description"] = description
            if vendor_id:
                payload["vendor_id"] = vendor_id
            resp = sess.post(f"{base}/expenses", params={"organization_id": org_id}, json=payload, timeout=20)
            resp.raise_for_status()
            result = resp.json()
            if result.get("code", 0) != 0:
                return {"status": "error", "message": result.get("message", "Unknown error"), "code": result.get("code")}
            e = result.get("expense", {})
            return {
                "id": e.get("expense_id", ""),
                "total": e.get("total", amount),
                "status": "created",
            }
        except Exception as exc:
            logger.error("Zoho Books create_expense error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_zoho_books_invoice(invoice_id: str, fields: dict) -> dict:
        """Update an existing Zoho Books invoice.

        Only works on draft invoices. Common updatable fields:
        date, due_date, notes, terms, line_items, custom_fields.

        Args:
            invoice_id: Zoho Books invoice ID.
            fields: Dict of fields to update.

        Returns:
            dict with invoice_id and status.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            resp = sess.put(
                f"{base}/invoices/{invoice_id}",
                params={"organization_id": org_id},
                json=fields,
                timeout=20,
            )
            resp.raise_for_status()
            return {"id": invoice_id, "status": "updated"}
        except Exception as exc:
            logger.error("Zoho Books update_invoice error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_zoho_books_contact(contact_id: str, fields: dict) -> dict:
        """Update a Zoho Books contact (customer or vendor).

        Args:
            contact_id: Zoho Books contact ID.
            fields: Dict of fields to update (contact_name, email, phone,
                    billing_address, etc.).

        Returns:
            dict with contact_id and status.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            resp = sess.put(
                f"{base}/contacts/{contact_id}",
                params={"organization_id": org_id},
                json=fields,
                timeout=20,
            )
            resp.raise_for_status()
            return {"id": contact_id, "status": "updated"}
        except Exception as exc:
            logger.error("Zoho Books update_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def mark_zoho_books_invoice_sent(invoice_id: str) -> dict:
        """Mark a Zoho Books invoice as sent (changes status from draft to sent).

        Args:
            invoice_id: Zoho Books invoice ID.

        Returns:
            dict with invoice_id and new status.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            resp = sess.post(
                f"{base}/invoices/{invoice_id}/status/sent",
                params={"organization_id": org_id},
                timeout=20,
            )
            resp.raise_for_status()
            return {"id": invoice_id, "status": "sent"}
        except Exception as exc:
            logger.error("Zoho Books mark_sent error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_zoho_books_invoice(invoice_id: str) -> dict:
        """Delete a Zoho Books invoice (only draft or void invoices can be deleted).

        Args:
            invoice_id: Zoho Books invoice ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            resp = sess.delete(f"{base}/invoices/{invoice_id}", params={"organization_id": org_id}, timeout=20)
            resp.raise_for_status()
            return {"id": invoice_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Zoho Books delete_invoice error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_zoho_books_contact(contact_id: str) -> dict:
        """Delete a Zoho Books contact (customer or vendor).

        Args:
            contact_id: Zoho Books contact ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            resp = sess.delete(f"{base}/contacts/{contact_id}", params={"organization_id": org_id}, timeout=20)
            resp.raise_for_status()
            return {"id": contact_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Zoho Books delete_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_zoho_books_expense(expense_id: str) -> dict:
        """Delete a Zoho Books expense record.

        Args:
            expense_id: Zoho Books expense ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("zoho_books")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho Books tool is currently disabled."}
        try:
            sess, base, org_id = _session(cfg.config)
            resp = sess.delete(f"{base}/expenses/{expense_id}", params={"organization_id": org_id}, timeout=20)
            resp.raise_for_status()
            return {"id": expense_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Zoho Books delete_expense error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_zoho_books_invoices,
        get_zoho_books_invoice,
        list_zoho_books_contacts,
        get_zoho_books_contact,
        list_zoho_books_expenses,
        get_zoho_books_expense,
        list_zoho_books_items,
        # Create
        create_zoho_books_invoice,
        create_zoho_books_contact,
        create_zoho_books_expense,
        # Update
        update_zoho_books_invoice,
        update_zoho_books_contact,
        mark_zoho_books_invoice_sent,
        # Delete
        delete_zoho_books_invoice,
        delete_zoho_books_contact,
        delete_zoho_books_expense,
    ]
