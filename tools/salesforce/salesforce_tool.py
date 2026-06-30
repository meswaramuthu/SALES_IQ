"""Salesforce tool — Salesforce REST API via simple-salesforce.

Required credentials (set in tools_config.json or env vars):
  username       : Salesforce username (email)
  password       : Salesforce user password
  security_token : Salesforce security token (reset at My Settings → Security Token)
  domain         : 'login' (production, default) or 'test' (sandbox)

  -- OR use OAuth2 connected app credentials --
  consumer_key    : Connected App consumer key
  consumer_secret : Connected App consumer secret
  instance_url    : e.g. https://yourorg.my.salesforce.com

In tools_config.json, reference secrets as:
  "password":       "env:SALESFORCE_PASSWORD"
  "security_token": "env:SALESFORCE_SECURITY_TOKEN"
  "consumer_key":   "env:SALESFORCE_CONSUMER_KEY"
  "consumer_secret":"env:SALESFORCE_CONSUMER_SECRET"

Tools exported:
  READ
    query_salesforce            - run SOQL query and return records
    get_salesforce_record       - get a single record by object type and ID
    list_salesforce_objects     - list available Salesforce objects (sObject types)
    describe_salesforce_object  - describe fields of a Salesforce object

  CREATE
    create_salesforce_record    - create a new record in any sObject
    create_salesforce_lead      - shortcut to create a Lead record
    create_salesforce_contact   - shortcut to create a Contact record

  UPDATE
    update_salesforce_record    - update fields of any sObject record
    upsert_salesforce_record    - upsert by external ID field

  DELETE
    delete_salesforce_record    - delete a record permanently
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _sf(cfg: dict):
    from simple_salesforce import Salesforce

    if cfg.get("consumer_key") and cfg.get("instance_url"):
        return Salesforce(
            consumer_key=cfg["consumer_key"],
            consumer_secret=cfg.get("consumer_secret", ""),
            instance_url=cfg["instance_url"],
        )
    return Salesforce(
        username=cfg.get("username", ""),
        password=cfg.get("password", ""),
        security_token=cfg.get("security_token", ""),
        domain=cfg.get("domain", "login"),
    )


def _clean(record: dict) -> dict:
    """Strip Salesforce metadata attributes from a record dict."""
    record.pop("attributes", None)
    return record


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def query_salesforce(soql: str) -> dict:
        """Run a SOQL query and return matching Salesforce records.

        Use this to search, filter, and aggregate data across any Salesforce object.

        Args:
            soql: SOQL query string. Examples:
                  "SELECT Id, Name, Email FROM Contact WHERE LastName = 'Smith' LIMIT 20"
                  "SELECT Id, Amount, StageName FROM Opportunity WHERE StageName = 'Closed Won'"
                  "SELECT Account.Name, COUNT(Id) FROM Contact GROUP BY Account.Name"

        Returns:
            dict with records list and totalSize.
        """
        cfg = get_config().tools.get("salesforce")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Salesforce tool is currently disabled."}
        try:
            sf = _sf(cfg.config)
            result = sf.query_all(soql)
            records = [_clean(dict(r)) for r in result.get("records", [])]
            return {"records": records, "total_size": result.get("totalSize", 0), "count": len(records)}
        except Exception as exc:
            logger.error("Salesforce query error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_salesforce_record(object_type: str, record_id: str) -> dict:
        """Get a single Salesforce record by object type and ID.

        Args:
            object_type: Salesforce sObject API name (e.g. 'Contact', 'Account',
                         'Lead', 'Opportunity', 'Case', 'Task').
            record_id: 15- or 18-character Salesforce record ID.

        Returns:
            dict with all field values for the record.
        """
        cfg = get_config().tools.get("salesforce")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Salesforce tool is currently disabled."}
        try:
            sf = _sf(cfg.config)
            sobject = getattr(sf, object_type)
            record = sobject.get(record_id)
            return _clean(dict(record))
        except Exception as exc:
            logger.error("Salesforce get_record error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_salesforce_objects() -> dict:
        """List all available Salesforce sObject types in the org.

        Returns:
            dict with list of objects (name, label, queryable, createable).
        """
        cfg = get_config().tools.get("salesforce")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Salesforce tool is currently disabled."}
        try:
            sf = _sf(cfg.config)
            result = sf.describe()
            objects = [
                {
                    "name": o["name"],
                    "label": o["label"],
                    "queryable": o.get("queryable", False),
                    "createable": o.get("createable", False),
                    "updateable": o.get("updateable", False),
                    "deletable": o.get("deletable", False),
                }
                for o in result.get("sobjects", [])
                if o.get("queryable")
            ]
            return {"objects": objects, "count": len(objects)}
        except Exception as exc:
            logger.error("Salesforce list_objects error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def describe_salesforce_object(object_type: str) -> dict:
        """Describe the fields of a Salesforce sObject.

        Use this to understand what fields exist before running queries or creating records.

        Args:
            object_type: Salesforce sObject API name (e.g. 'Contact', 'Opportunity').

        Returns:
            dict with list of fields (name, label, type, required, length).
        """
        cfg = get_config().tools.get("salesforce")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Salesforce tool is currently disabled."}
        try:
            sf = _sf(cfg.config)
            sobject = getattr(sf, object_type)
            result = sobject.describe()
            fields = [
                {
                    "name": f["name"],
                    "label": f["label"],
                    "type": f["type"],
                    "required": not f.get("nillable", True) and f.get("createable", False),
                    "length": f.get("length", 0),
                    "picklist_values": [v["value"] for v in f.get("picklistValues", [])] if f.get("picklistValues") else [],
                }
                for f in result.get("fields", [])
            ]
            return {"object_type": object_type, "fields": fields, "count": len(fields)}
        except Exception as exc:
            logger.error("Salesforce describe_object error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_salesforce_record(object_type: str, fields: dict) -> dict:
        """Create a new record in any Salesforce sObject.

        Use describe_salesforce_object first to check required fields.

        Args:
            object_type: Salesforce sObject API name (e.g. 'Contact', 'Account',
                         'Lead', 'Opportunity', 'Case').
            fields: Dict of field name → value. API field names required
                    (e.g. 'FirstName', 'LastName', 'Email', 'AccountId').

        Returns:
            dict with created record ID, success status, and errors if any.
        """
        cfg = get_config().tools.get("salesforce")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Salesforce tool is currently disabled."}
        try:
            sf = _sf(cfg.config)
            sobject = getattr(sf, object_type)
            result = sobject.create(fields)
            return {
                "id": result.get("id", ""),
                "success": result.get("success", False),
                "errors": result.get("errors", []),
                "status": "created",
            }
        except Exception as exc:
            logger.error("Salesforce create_record error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_salesforce_lead(
        first_name: str,
        last_name: str,
        email: str,
        company: str,
        phone: str = "",
        lead_source: str = "",
        description: str = "",
    ) -> dict:
        """Create a new Lead in Salesforce.

        Args:
            first_name: Lead first name.
            last_name: Lead last name.
            email: Lead email address.
            company: Company name (required for Leads).
            phone: Phone number. Optional.
            lead_source: Lead source (e.g. 'Web', 'Email', 'Phone', 'Partner',
                         'Event', 'Cold Call'). Optional.
            description: Additional notes. Optional.

        Returns:
            dict with created lead ID and status.
        """
        cfg = get_config().tools.get("salesforce")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Salesforce tool is currently disabled."}
        try:
            sf = _sf(cfg.config)
            payload: dict = {
                "FirstName": first_name,
                "LastName": last_name,
                "Email": email,
                "Company": company,
            }
            if phone:
                payload["Phone"] = phone
            if lead_source:
                payload["LeadSource"] = lead_source
            if description:
                payload["Description"] = description
            result = sf.Lead.create(payload)
            return {"id": result.get("id", ""), "success": result.get("success", False), "status": "created"}
        except Exception as exc:
            logger.error("Salesforce create_lead error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def create_salesforce_contact(
        first_name: str,
        last_name: str,
        email: str,
        account_id: str = "",
        phone: str = "",
        title: str = "",
    ) -> dict:
        """Create a new Contact in Salesforce.

        Args:
            first_name: Contact first name.
            last_name: Contact last name.
            email: Contact email address.
            account_id: ID of the related Account. Leave blank to create standalone.
            phone: Phone number. Optional.
            title: Job title. Optional.

        Returns:
            dict with created contact ID and status.
        """
        cfg = get_config().tools.get("salesforce")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Salesforce tool is currently disabled."}
        try:
            sf = _sf(cfg.config)
            payload: dict = {"FirstName": first_name, "LastName": last_name, "Email": email}
            if account_id:
                payload["AccountId"] = account_id
            if phone:
                payload["Phone"] = phone
            if title:
                payload["Title"] = title
            result = sf.Contact.create(payload)
            return {"id": result.get("id", ""), "success": result.get("success", False), "status": "created"}
        except Exception as exc:
            logger.error("Salesforce create_contact error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_salesforce_record(object_type: str, record_id: str, fields: dict) -> dict:
        """Update fields of an existing Salesforce record.

        Only the fields you supply are changed; omitted fields stay as-is.

        Args:
            object_type: Salesforce sObject API name (e.g. 'Contact', 'Opportunity').
            record_id: 15- or 18-character Salesforce record ID.
            fields: Dict of field name → new value.
                    Example: {"StageName": "Closed Won", "CloseDate": "2025-12-31"}

        Returns:
            dict with record_id and HTTP status code (204 = success).
        """
        cfg = get_config().tools.get("salesforce")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Salesforce tool is currently disabled."}
        try:
            sf = _sf(cfg.config)
            sobject = getattr(sf, object_type)
            result = sobject.update(record_id, fields)
            return {
                "id": record_id,
                "http_status": result,
                "status": "updated" if result == 204 else "partial",
            }
        except Exception as exc:
            logger.error("Salesforce update_record error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def upsert_salesforce_record(
        object_type: str,
        external_id_field: str,
        external_id_value: str,
        fields: dict,
    ) -> dict:
        """Upsert a Salesforce record by an external ID field.

        Creates the record if it doesn't exist, updates it if it does.

        Args:
            object_type: Salesforce sObject API name.
            external_id_field: The API name of the external ID field
                               (e.g. 'External_ID__c', 'Email').
            external_id_value: The value to match against the external ID field.
            fields: Dict of field name → value to set on create or update.

        Returns:
            dict with record id and whether it was created or updated.
        """
        cfg = get_config().tools.get("salesforce")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Salesforce tool is currently disabled."}
        try:
            sf = _sf(cfg.config)
            sobject = getattr(sf, object_type)
            result = sobject.upsert(f"{external_id_field}/{external_id_value}", fields)
            return {
                "id": result.get("id", ""),
                "created": result.get("created", False),
                "status": "created" if result.get("created") else "updated",
            }
        except Exception as exc:
            logger.error("Salesforce upsert_record error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_salesforce_record(object_type: str, record_id: str) -> dict:
        """Permanently delete a Salesforce record.

        WARNING: This is irreversible in production orgs. The record and its
        related data will be permanently removed.

        Args:
            object_type: Salesforce sObject API name (e.g. 'Contact', 'Lead').
            record_id: 15- or 18-character Salesforce record ID.

        Returns:
            dict confirming deletion (HTTP 204 = success).
        """
        cfg = get_config().tools.get("salesforce")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Salesforce tool is currently disabled."}
        try:
            sf = _sf(cfg.config)
            sobject = getattr(sf, object_type)
            result = sobject.delete(record_id)
            return {
                "id": record_id,
                "http_status": result,
                "status": "deleted" if result == 204 else "error",
            }
        except Exception as exc:
            logger.error("Salesforce delete_record error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        query_salesforce,
        get_salesforce_record,
        list_salesforce_objects,
        describe_salesforce_object,
        # Create
        create_salesforce_record,
        create_salesforce_lead,
        create_salesforce_contact,
        # Update
        update_salesforce_record,
        upsert_salesforce_record,
        # Delete
        delete_salesforce_record,
    ]
