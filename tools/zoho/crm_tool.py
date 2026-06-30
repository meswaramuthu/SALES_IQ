"""Zoho CRM tool — Zoho CRM REST API v6.

Required credentials (set in tools_config.json):
  client_id     : Zoho OAuth2 client ID
  client_secret : Zoho OAuth2 client secret
  refresh_token : Zoho OAuth2 refresh token (permanent — never needs rotation)
  base_url      : API base URL for your data centre
                    https://www.zohoapis.com    (US, default)
                    https://www.zohoapis.eu     (EU)
                    https://www.zohoapis.in     (IN)
                    https://www.zohoapis.com.au (AU)
  accounts_url  : (optional) Zoho accounts domain for token refresh
                    https://accounts.zoho.com  (default)
                    https://accounts.zoho.eu / .in / .com.au for other DCs

In tools_config.json, reference secrets as:
  "client_id":     "env:ZOHO_CLIENT_ID"
  "client_secret": "env:ZOHO_CLIENT_SECRET"
  "refresh_token": "env:ZOHO_REFRESH_TOKEN"

The access token is fetched and cached automatically; it never needs to be
stored or rotated manually.

Tools exported:
  READ
    search_zoho_crm_records  - search records in any module by criteria or keyword
    get_zoho_crm_record      - get a single record by module and ID
    list_zoho_crm_records    - list records in a module with optional field selection
    list_zoho_crm_modules    - list all available CRM modules

  CREATE
    create_zoho_crm_record   - create a record in any module (Lead, Contact, Account, Deal...)
    create_zoho_crm_note     - attach a note to a CRM record

  UPDATE
    update_zoho_crm_record   - update fields of an existing CRM record
    convert_zoho_crm_lead    - convert a Lead to Contact/Account/Deal

  DELETE
    delete_zoho_crm_record   - permanently delete a CRM record
    delete_zoho_crm_records  - bulk-delete multiple records
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
    return sess, cfg.get("base_url", "https://www.zohoapis.com").rstrip("/")


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_zoho_crm_records(
        module: str,
        fields: str = "",
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """List records from a Zoho CRM module.

        Args:
            module: CRM module API name — 'Leads', 'Contacts', 'Accounts',
                    'Deals', 'Tasks', 'Calls', 'Meetings', 'Cases', etc.
            fields: Comma-separated field API names to return. Leave blank
                    to return all default fields.
            page: Page number for pagination (default 1).
            per_page: Records per page (default 20, max 200).

        Returns:
            dict with list of records and pagination info.
        """
        cfg = get_config().tools.get("zoho_crm")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho CRM tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            params: dict = {"page": page, "per_page": per_page}
            if fields:
                params["fields"] = fields
            resp = sess.get(f"{base}/crm/v6/{module}", params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            records = data.get("data", [])
            info = data.get("info", {})
            return {
                "records": records,
                "count": len(records),
                "page": info.get("page", page),
                "more_records": info.get("more_records", False),
            }
        except Exception as exc:
            logger.error("Zoho CRM list_records error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def search_zoho_crm_records(
        module: str,
        criteria: str = "",
        word: str = "",
        email: str = "",
        phone: str = "",
        per_page: int = 20,
    ) -> dict:
        """Search Zoho CRM records in a module.

        Provide exactly one of: criteria, word, email, or phone.

        Args:
            module: CRM module — 'Leads', 'Contacts', 'Accounts', 'Deals', etc.
            criteria: COQL-style criteria string for advanced filtering.
                      Example: "(Last_Name:equals:Smith)and(Lead_Status:equals:New)"
            word: Free-text keyword search across all searchable fields.
            email: Search by exact email address.
            phone: Search by exact phone number.
            per_page: Number of results (default 20, max 200).

        Returns:
            dict with list of matching records.
        """
        cfg = get_config().tools.get("zoho_crm")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho CRM tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            params: dict = {"per_page": per_page}
            if criteria:
                params["criteria"] = criteria
            elif word:
                params["word"] = word
            elif email:
                params["email"] = email
            elif phone:
                params["phone"] = phone
            else:
                return {"status": "error", "message": "Provide at least one of: criteria, word, email, phone."}
            resp = sess.get(f"{base}/crm/v6/{module}/search", params=params, timeout=20)
            if resp.status_code == 204:
                return {"records": [], "count": 0}
            resp.raise_for_status()
            data = resp.json()
            records = data.get("data", [])
            return {"records": records, "count": len(records)}
        except Exception as exc:
            logger.error("Zoho CRM search error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_zoho_crm_record(module: str, record_id: str) -> dict:
        """Get a single Zoho CRM record by module and ID.

        Args:
            module: CRM module API name (e.g. 'Leads', 'Contacts', 'Deals').
            record_id: Zoho CRM record ID (numeric string).

        Returns:
            dict with all record fields.
        """
        cfg = get_config().tools.get("zoho_crm")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho CRM tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/crm/v6/{module}/{record_id}", timeout=20)
            resp.raise_for_status()
            data = resp.json()
            records = data.get("data", [])
            return records[0] if records else {"status": "not_found"}
        except Exception as exc:
            logger.error("Zoho CRM get_record error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zoho_crm_modules() -> dict:
        """List all available Zoho CRM modules in the org.

        Returns:
            dict with list of modules (api_name, singular_label, plural_label).
        """
        cfg = get_config().tools.get("zoho_crm")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho CRM tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/crm/v6/settings/modules", timeout=20)
            resp.raise_for_status()
            mods = resp.json().get("modules", [])
            modules = [
                {
                    "api_name": m.get("api_name", ""),
                    "singular_label": m.get("singular_label", ""),
                    "plural_label": m.get("plural_label", ""),
                    "status": m.get("status", ""),
                }
                for m in mods
            ]
            return {"modules": modules, "count": len(modules)}
        except Exception as exc:
            logger.error("Zoho CRM list_modules error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_zoho_crm_record(module: str, fields: dict) -> dict:
        """Create a new record in a Zoho CRM module.

        Args:
            module: CRM module API name (e.g. 'Leads', 'Contacts', 'Accounts', 'Deals').
            fields: Dict of field API name → value.
                    Required fields vary by module. Common required fields:
                    Leads: Last_Name, Company
                    Contacts: Last_Name
                    Accounts: Account_Name
                    Deals: Deal_Name, Stage, Closing_Date, Account_Name (dict ref)

        Returns:
            dict with created record id, status, and any duplicate warnings.
        """
        cfg = get_config().tools.get("zoho_crm")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho CRM tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.post(
                f"{base}/crm/v6/{module}",
                json={"data": [fields]},
                timeout=20,
            )
            resp.raise_for_status()
            result = resp.json().get("data", [{}])[0]
            return {
                "id": result.get("details", {}).get("id", ""),
                "code": result.get("code", ""),
                "message": result.get("message", ""),
                "status": "created" if result.get("code") == "SUCCESS" else result.get("code", "error"),
            }
        except Exception as exc:
            logger.error("Zoho CRM create_record error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_zoho_crm_note(module: str, record_id: str, title: str, content: str) -> dict:
        """Attach a note to a Zoho CRM record.

        Args:
            module: CRM module of the parent record (e.g. 'Leads', 'Contacts').
            record_id: Parent record ID.
            title: Note title.
            content: Note body text.

        Returns:
            dict with created note id and status.
        """
        cfg = get_config().tools.get("zoho_crm")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho CRM tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload = {
                "data": [{
                    "Note_Title": title,
                    "Note_Content": content,
                    "Parent_Id": {"id": record_id},
                    "$se_module": module,
                }]
            }
            resp = sess.post(f"{base}/crm/v6/Notes", json=payload, timeout=20)
            resp.raise_for_status()
            result = resp.json().get("data", [{}])[0]
            return {
                "id": result.get("details", {}).get("id", ""),
                "status": "created" if result.get("code") == "SUCCESS" else result.get("code", "error"),
            }
        except Exception as exc:
            logger.error("Zoho CRM create_note error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_zoho_crm_record(module: str, record_id: str, fields: dict) -> dict:
        """Update fields of an existing Zoho CRM record.

        Only the provided fields are modified; others stay unchanged.

        Args:
            module: CRM module API name.
            record_id: Zoho CRM record ID.
            fields: Dict of field API name → new value.

        Returns:
            dict with record id and update status.
        """
        cfg = get_config().tools.get("zoho_crm")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho CRM tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload = {"data": [fields]}
            resp = sess.put(f"{base}/crm/v6/{module}/{record_id}", json=payload, timeout=20)
            resp.raise_for_status()
            result = resp.json().get("data", [{}])[0]
            return {
                "id": record_id,
                "code": result.get("code", ""),
                "status": "updated" if result.get("code") == "SUCCESS" else result.get("code", "error"),
            }
        except Exception as exc:
            logger.error("Zoho CRM update_record error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def convert_zoho_crm_lead(
        lead_id: str,
        overwrite: bool = False,
        notify_lead_owner: bool = True,
        notify_new_entity_owner: bool = True,
    ) -> dict:
        """Convert a Zoho CRM Lead to a Contact, Account, and/or Deal.

        Args:
            lead_id: ID of the Lead record to convert.
            overwrite: If True, overwrite existing Contact/Account fields with Lead data.
            notify_lead_owner: Send notification to the lead owner. Default True.
            notify_new_entity_owner: Send notification to new Contact/Account/Deal owner.

        Returns:
            dict with created Contact, Account, and Deal IDs.
        """
        cfg = get_config().tools.get("zoho_crm")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho CRM tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload = {
                "data": [{
                    "overwrite": overwrite,
                    "notify_lead_owner": notify_lead_owner,
                    "notify_new_entity_owner": notify_new_entity_owner,
                }]
            }
            resp = sess.post(f"{base}/crm/v6/Leads/{lead_id}/actions/convert", json=payload, timeout=20)
            resp.raise_for_status()
            result = resp.json().get("data", [{}])[0]
            return {
                "contact": result.get("Contact", {}).get("id", ""),
                "account": result.get("Account", {}).get("id", ""),
                "deal": result.get("Deal", {}).get("id", ""),
                "status": "converted",
            }
        except Exception as exc:
            logger.error("Zoho CRM convert_lead error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_zoho_crm_record(module: str, record_id: str) -> dict:
        """Permanently delete a Zoho CRM record.

        Args:
            module: CRM module API name.
            record_id: Zoho CRM record ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("zoho_crm")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho CRM tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.delete(f"{base}/crm/v6/{module}?ids={record_id}", timeout=20)
            resp.raise_for_status()
            result = resp.json().get("data", [{}])[0]
            return {
                "id": record_id,
                "status": "deleted" if result.get("code") == "SUCCESS" else result.get("code", "error"),
            }
        except Exception as exc:
            logger.error("Zoho CRM delete_record error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_zoho_crm_records(module: str, record_ids: list[str]) -> dict:
        """Bulk-delete multiple Zoho CRM records (up to 100 at once).

        Args:
            module: CRM module API name.
            record_ids: List of record IDs to delete (max 100).

        Returns:
            dict with per-record deletion status.
        """
        cfg = get_config().tools.get("zoho_crm")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho CRM tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            ids_param = ",".join(record_ids[:100])
            resp = sess.delete(f"{base}/crm/v6/{module}?ids={ids_param}", timeout=30)
            resp.raise_for_status()
            results = [
                {"id": r.get("details", {}).get("id", ""), "code": r.get("code", "")}
                for r in resp.json().get("data", [])
            ]
            return {"results": results, "count": len(results), "status": "processed"}
        except Exception as exc:
            logger.error("Zoho CRM bulk_delete error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_zoho_crm_records,
        search_zoho_crm_records,
        get_zoho_crm_record,
        list_zoho_crm_modules,
        # Create
        create_zoho_crm_record,
        create_zoho_crm_note,
        # Update
        update_zoho_crm_record,
        convert_zoho_crm_lead,
        # Delete
        delete_zoho_crm_record,
        delete_zoho_crm_records,
    ]
