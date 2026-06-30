"""Workday tool — Workday REST API v1.

Required credentials (set in tools_config.json or env vars):
  base_url      : Workday REST API base URL, e.g.
                  https://{tenant}.workday.com/api/v1/{tenant}
                  (visible in Workday: Tools → Workday REST API Endpoint)
  access_token  : Bearer access token from Workday OAuth2 (IS/OAuth2 Clients)
  tenant        : Workday tenant name (also called namespace), e.g. 'mycompany'

  -- For OAuth2 Client Credentials grant (service-to-service) --
  client_id     : OAuth2 client ID
  client_secret : OAuth2 client secret
  token_url     : Token endpoint, e.g. https://{tenant}.workday.com/ccx/oauth2/{tenant}/token

In tools_config.json, reference secrets as:
  "access_token":  "env:WORKDAY_ACCESS_TOKEN"
  "client_id":     "env:WORKDAY_CLIENT_ID"
  "client_secret": "env:WORKDAY_CLIENT_SECRET"

Note: Workday REST API coverage is limited compared to SOAP. For worker reads
and org data, REST is fully supported. Mutations (hire, terminate) may require
SOAP or Workday Extend depending on tenant configuration.

Tools exported:
  READ
    list_workday_workers        - list all active workers/employees
    get_workday_worker          - get a single worker by ID
    search_workday_workers      - search workers by name or email
    list_workday_organizations  - list organizations (companies, cost centers)
    list_workday_job_profiles   - list available job profiles

  CREATE
    create_workday_worker_note  - add a note/comment to a worker profile

  UPDATE
    update_workday_worker       - update worker contact info or custom fields

  DELETE
    (Workday REST API does not support hard deletion of worker records;
     terminations are handled through business process APIs)
    terminate_workday_worker    - initiate termination business process for a worker
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _session(cfg: dict):
    import requests
    sess = requests.Session()
    access_token = cfg.get("access_token", "")
    if not access_token and cfg.get("client_id"):
        token_url = cfg.get("token_url", "")
        if not token_url:
            raise ValueError("Workday token_url is required for OAuth2 client credentials flow but is not configured.")
        r = requests.post(
            token_url,
            data={"grant_type": "client_credentials"},
            auth=(cfg["client_id"], cfg.get("client_secret", "")),
            timeout=15,
        )
        r.raise_for_status()
        access_token = r.json().get("access_token", "")
    sess.headers.update({
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    })
    base = cfg.get("base_url", "").rstrip("/")
    return sess, base


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_workday_workers(limit: int = 50, offset: int = 0) -> dict:
        """List active workers (employees) in Workday.

        Args:
            limit: Number of workers to return (default 50, max 100).
            offset: Offset for pagination (default 0).

        Returns:
            dict with list of workers (id, name, email, jobTitle, location, managerId).
        """
        cfg = get_config().tools.get("workday")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Workday tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(
                f"{base}/workers",
                params={"limit": limit, "offset": offset},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            workers = [
                {
                    "id": w.get("id", ""),
                    "descriptor": w.get("descriptor", ""),
                    "href": w.get("href", ""),
                }
                for w in data.get("data", [])
            ]
            return {"workers": workers, "count": len(workers), "total": data.get("total", len(workers))}
        except Exception as exc:
            logger.error("Workday list_workers error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_workday_worker(worker_id: str) -> dict:
        """Get full profile of a single Workday worker.

        Args:
            worker_id: Workday worker ID (GUID or reference ID).

        Returns:
            dict with worker profile including job, location, manager, and contact info.
        """
        cfg = get_config().tools.get("workday")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Workday tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/workers/{worker_id}", timeout=20)
            resp.raise_for_status()
            w = resp.json()
            return {
                "id": w.get("id", ""),
                "descriptor": w.get("descriptor", ""),
                "person": w.get("person", {}),
                "primaryJob": w.get("primaryJob", {}),
                "allPositions": w.get("allPositions", []),
                "href": w.get("href", ""),
            }
        except Exception as exc:
            logger.error("Workday get_worker error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def search_workday_workers(query: str, limit: int = 20) -> dict:
        """Search Workday workers by name or other attributes.

        Args:
            query: Search string (name fragment, email, etc.).
            limit: Maximum results (default 20).

        Returns:
            dict with list of matching workers.
        """
        cfg = get_config().tools.get("workday")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Workday tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(
                f"{base}/workers",
                params={"search": query, "limit": limit},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            workers = [
                {"id": w.get("id", ""), "descriptor": w.get("descriptor", ""), "href": w.get("href", "")}
                for w in data.get("data", [])
            ]
            return {"workers": workers, "count": len(workers)}
        except Exception as exc:
            logger.error("Workday search_workers error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_workday_organizations(organization_type: str = "", limit: int = 50) -> dict:
        """List Workday organizations (companies, cost centers, departments).

        Args:
            organization_type: Filter by type — 'Company', 'Cost_Center',
                               'Supervisory'. Leave blank for all.
            limit: Max organizations to return (default 50).

        Returns:
            dict with list of organizations (id, name, type).
        """
        cfg = get_config().tools.get("workday")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Workday tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            params: dict = {"limit": limit}
            if organization_type:
                params["type"] = organization_type
            resp = sess.get(f"{base}/organizations", params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            orgs = [
                {"id": o.get("id", ""), "descriptor": o.get("descriptor", ""), "href": o.get("href", "")}
                for o in data.get("data", [])
            ]
            return {"organizations": orgs, "count": len(orgs), "total": data.get("total", len(orgs))}
        except Exception as exc:
            logger.error("Workday list_organizations error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_workday_job_profiles(limit: int = 50) -> dict:
        """List available Workday job profiles.

        Args:
            limit: Max job profiles to return (default 50).

        Returns:
            dict with list of job profiles (id, descriptor).
        """
        cfg = get_config().tools.get("workday")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Workday tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/jobProfiles", params={"limit": limit}, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            profiles = [
                {"id": p.get("id", ""), "descriptor": p.get("descriptor", "")}
                for p in data.get("data", [])
            ]
            return {"job_profiles": profiles, "count": len(profiles)}
        except Exception as exc:
            logger.error("Workday list_job_profiles error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_workday_worker_note(worker_id: str, note: str, subject: str = "") -> dict:
        """Add a note/comment to a Workday worker profile.

        Args:
            worker_id: Workday worker ID.
            note: Note body text.
            subject: Note subject/title. Optional.

        Returns:
            dict with note id and status.
        """
        cfg = get_config().tools.get("workday")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Workday tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {"comment": note}
            if subject:
                payload["subject"] = subject
            resp = sess.post(f"{base}/workers/{worker_id}/notes", json=payload, timeout=20)
            resp.raise_for_status()
            result = resp.json()
            return {"id": result.get("id", ""), "status": "created"}
        except Exception as exc:
            logger.error("Workday create_worker_note error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_workday_worker(worker_id: str, fields: dict) -> dict:
        """Update contact or custom field data for a Workday worker.

        Supports updates to: workEmail, workPhone, workAddress, and
        any custom extended data fields available in your tenant.

        Args:
            worker_id: Workday worker ID.
            fields: Dict of fields to update. Keys follow Workday REST API
                    field names for the worker object.

        Returns:
            dict with worker_id and status.
        """
        cfg = get_config().tools.get("workday")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Workday tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.patch(f"{base}/workers/{worker_id}", json=fields, timeout=20)
            resp.raise_for_status()
            return {"id": worker_id, "status": "updated"}
        except Exception as exc:
            logger.error("Workday update_worker error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE (Terminate) ────────────────────────────────────────────────────

    def terminate_workday_worker(
        worker_id: str,
        termination_date: str,
        reason_id: str = "",
        regrettable: bool = False,
    ) -> dict:
        """Initiate a termination business process for a Workday worker.

        This starts the Workday termination workflow; it may require manager
        approval depending on your tenant's BP configuration.

        Args:
            worker_id: Workday worker ID.
            termination_date: Last day of employment in YYYY-MM-DD format.
            reason_id: Termination reason reference ID from your Workday tenant.
                       Leave blank to use the tenant default.
            regrettable: Mark the termination as regrettable. Default False.

        Returns:
            dict with workflow event ID and status.
        """
        cfg = get_config().tools.get("workday")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Workday tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {
                "terminationDate": termination_date,
                "regrettable": regrettable,
            }
            if reason_id:
                payload["terminationReason"] = {"id": reason_id}
            resp = sess.post(f"{base}/workers/{worker_id}/terminate", json=payload, timeout=20)
            resp.raise_for_status()
            result = resp.json()
            return {
                "id": result.get("id", ""),
                "worker_id": worker_id,
                "termination_date": termination_date,
                "status": "termination_initiated",
            }
        except Exception as exc:
            logger.error("Workday terminate_worker error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_workday_workers,
        get_workday_worker,
        search_workday_workers,
        list_workday_organizations,
        list_workday_job_profiles,
        # Create
        create_workday_worker_note,
        # Update
        update_workday_worker,
        # Delete / Terminate
        terminate_workday_worker,
    ]
