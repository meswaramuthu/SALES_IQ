"""BambooHR tool — BambooHR REST API v1.

Required credentials (set in tools_config.json or env vars):
  api_key        : BambooHR API key (My Info → API Keys in BambooHR)
  company_domain : Your BambooHR company subdomain (e.g. 'mycompany' for mycompany.bamboohr.com)

In tools_config.json, reference secrets as:
  "api_key":        "env:BAMBOOHR_API_KEY"
  "company_domain": "env:BAMBOOHR_COMPANY_DOMAIN"

Tools exported:
  READ
    list_bamboohr_employees        - list all employees from the directory
    get_bamboohr_employee          - get a single employee with all fields
    get_bamboohr_employee_fields   - list all available employee fields
    list_bamboohr_time_off_types   - list time-off policy types
    list_bamboohr_time_off_requests - list time-off requests with filters
    get_bamboohr_who_is_out        - get who is out today or on a date range

  CREATE
    create_bamboohr_employee       - add a new employee record
    request_bamboohr_time_off      - submit a time-off request for an employee

  UPDATE
    update_bamboohr_employee       - update employee fields
    update_bamboohr_time_off_status - approve, deny, or cancel a time-off request

  DELETE
    delete_bamboohr_employee       - deactivate/terminate an employee record
    delete_bamboohr_time_off       - cancel/delete a time-off request
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)


def _session(cfg: dict):
    import requests
    api_key = cfg.get("api_key", "")
    domain = cfg.get("company_domain", "").rstrip("/")
    sess = requests.Session()
    sess.auth = (api_key, "x")
    sess.headers.update({"Accept": "application/json"})
    base = f"https://api.bamboohr.com/api/gateway.php/{domain}/v1"
    return sess, base


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_bamboohr_employees(fields: str = "") -> dict:
        """List all employees from the BambooHR directory.

        Args:
            fields: Comma-separated list of fields to return.
                    Common fields: firstName, lastName, workEmail, jobTitle,
                    department, location, supervisor, hireDate, employeeNumber.
                    Leave blank for default directory fields.

        Returns:
            dict with list of employees.
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            default_fields = fields or "firstName,lastName,workEmail,jobTitle,department,location,hireDate,employeeNumber,supervisor,status"
            resp = sess.get(
                f"{base}/employees/directory",
                params={"fields": default_fields},
                timeout=20,
            )
            resp.raise_for_status()
            employees = resp.json().get("employees", [])
            return {"employees": employees, "count": len(employees)}
        except Exception as exc:
            logger.error("BambooHR list_employees error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_bamboohr_employee(employee_id: str, fields: str = "") -> dict:
        """Get a single BambooHR employee by ID with all or specific fields.

        Args:
            employee_id: BambooHR employee ID (numeric string or 0 for self).
            fields: Comma-separated field names to fetch. Leave blank for all
                    available fields.

        Returns:
            dict with employee fields.
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            default_fields = fields or "firstName,lastName,workEmail,jobTitle,department,location,hireDate,mobilePhone,workPhone,supervisor,employmentHistoryStatus,employeeNumber,maritalStatus,gender"
            resp = sess.get(
                f"{base}/employees/{employee_id}",
                params={"fields": default_fields},
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("BambooHR get_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_bamboohr_employee_fields() -> dict:
        """List all available employee fields in BambooHR.

        Returns:
            dict with list of fields (id, name, type, alias).
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/meta/fields", timeout=20)
            resp.raise_for_status()
            fields = [
                {
                    "id": f.get("id", ""),
                    "name": f.get("name", ""),
                    "type": f.get("type", ""),
                    "alias": f.get("alias", ""),
                }
                for f in resp.json()
            ]
            return {"fields": fields, "count": len(fields)}
        except Exception as exc:
            logger.error("BambooHR get_fields error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_bamboohr_time_off_types() -> dict:
        """List all time-off (leave) policy types in BambooHR.

        Returns:
            dict with list of time-off types (id, name, units).
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/meta/time_off/types", timeout=20)
            resp.raise_for_status()
            types = [
                {"id": t.get("id", ""), "name": t.get("name", ""), "units": t.get("units", "days")}
                for t in resp.json().get("timeOffTypes", [])
            ]
            return {"time_off_types": types, "count": len(types)}
        except Exception as exc:
            logger.error("BambooHR list_time_off_types error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_bamboohr_time_off_requests(
        start_date: str,
        end_date: str,
        status: str = "",
        employee_id: str = "",
    ) -> dict:
        """List BambooHR time-off requests in a date range.

        Args:
            start_date: Range start date in YYYY-MM-DD format.
            end_date: Range end date in YYYY-MM-DD format.
            status: Filter by status — 'approved', 'denied', 'superceded',
                    'requested', 'canceled'. Leave blank for all.
            employee_id: Filter by specific employee ID. Leave blank for all.

        Returns:
            dict with list of time-off requests.
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            params: dict = {"start": start_date, "end": end_date}
            if status:
                params["status"] = status
            if employee_id:
                params["employeeId"] = employee_id
            resp = sess.get(f"{base}/time_off/requests", params=params, timeout=20)
            resp.raise_for_status()
            requests_data = resp.json()
            if isinstance(requests_data, list):
                raw = requests_data
            elif isinstance(requests_data, dict):
                raw = requests_data.get("requests", requests_data.get("timeOffRequests", []))
            else:
                raw = []
            requests_list = [
                {
                    "id": r.get("id", ""),
                    "employee_id": r.get("employee", {}).get("id", ""),
                    "employee_name": r.get("employee", {}).get("name", ""),
                    "type": r.get("type", {}).get("name", ""),
                    "status": r.get("status", {}).get("status", ""),
                    "start": r.get("start", ""),
                    "end": r.get("end", ""),
                    "amount": r.get("amount", {}).get("amount", ""),
                    "notes": r.get("notes", {}).get("employee", {}).get("note", ""),
                }
                for r in raw
            ]
            return {"requests": requests_list, "count": len(requests_list)}
        except Exception as exc:
            logger.error("BambooHR list_time_off_requests error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_bamboohr_who_is_out(start_date: str = "", end_date: str = "") -> dict:
        """Get a list of employees who are out on a given date or date range.

        Args:
            start_date: Date in YYYY-MM-DD format. Defaults to today if blank.
            end_date: End date in YYYY-MM-DD format. Defaults to start_date.

        Returns:
            dict with list of employees who are out and their time-off details.
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            params: dict = {}
            if start_date:
                params["start"] = start_date
            if end_date:
                params["end"] = end_date
            resp = sess.get(f"{base}/time_off/whos_out", params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            out_list = [
                {
                    "id": r.get("id", ""),
                    "type": r.get("type", ""),
                    "employee_id": r.get("employeeId", ""),
                    "name": r.get("name", ""),
                    "start": r.get("start", ""),
                    "end": r.get("end", ""),
                }
                for r in (data if isinstance(data, list) else [])
            ]
            return {"out": out_list, "count": len(out_list)}
        except Exception as exc:
            logger.error("BambooHR who_is_out error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_bamboohr_employee(
        first_name: str,
        last_name: str,
        work_email: str,
        hire_date: str,
        department: str = "",
        job_title: str = "",
        location: str = "",
    ) -> dict:
        """Add a new employee record to BambooHR.

        Args:
            first_name: Employee first name.
            last_name: Employee last name.
            work_email: Work email address.
            hire_date: Hire date in YYYY-MM-DD format.
            department: Department name. Optional.
            job_title: Job title. Optional.
            location: Work location. Optional.

        Returns:
            dict with created employee ID.
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {
                "firstName": first_name,
                "lastName": last_name,
                "workEmail": work_email,
                "hireDate": hire_date,
            }
            if department:
                payload["department"] = department
            if job_title:
                payload["jobTitle"] = job_title
            if location:
                payload["location"] = location
            resp = sess.post(
                f"{base}/employees",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            employee_id = resp.headers.get("Location", "").rstrip("/").split("/")[-1]
            return {"id": employee_id, "status": "created"}
        except Exception as exc:
            logger.error("BambooHR create_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def request_bamboohr_time_off(
        employee_id: str,
        time_off_type_id: str,
        start_date: str,
        end_date: str,
        note: str = "",
    ) -> dict:
        """Submit a time-off request for a BambooHR employee.

        Args:
            employee_id: BambooHR employee ID.
            time_off_type_id: Time-off type ID (from list_bamboohr_time_off_types).
            start_date: First day of time off in YYYY-MM-DD format.
            end_date: Last day of time off in YYYY-MM-DD format.
            note: Optional note/reason for the request.

        Returns:
            dict with request ID and status.
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {
                "start": start_date,
                "end": end_date,
                "timeOffTypeId": int(time_off_type_id),
                "employeeId": int(employee_id),
            }
            if note:
                payload["note"] = note
            resp = sess.post(
                f"{base}/time_off/requests",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            return {"status": "requested", "employee_id": employee_id}
        except Exception as exc:
            logger.error("BambooHR request_time_off error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_bamboohr_employee(employee_id: str, fields: dict) -> dict:
        """Update fields of a BambooHR employee record.

        Only the provided fields are changed; others stay as-is.

        Args:
            employee_id: BambooHR employee ID.
            fields: Dict of field name → new value. Use BambooHR API field names
                    (e.g. 'jobTitle', 'department', 'mobilePhone', 'supervisor').
                    Use get_bamboohr_employee_fields to see all available fields.

        Returns:
            dict with employee_id and status.
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.post(
                f"{base}/employees/{employee_id}",
                json=fields,
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            return {"id": employee_id, "status": "updated"}
        except Exception as exc:
            logger.error("BambooHR update_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_bamboohr_time_off_status(
        request_id: str,
        status: str,
        note: str = "",
    ) -> dict:
        """Approve, deny, or cancel a BambooHR time-off request.

        Args:
            request_id: Time-off request ID.
            status: New status — 'approved', 'denied', or 'canceled'.
            note: Optional note explaining the decision.

        Returns:
            dict with request_id and new status.
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {"status": status}
            if note:
                payload["note"] = note
            resp = sess.post(
                f"{base}/time_off/requests/{request_id}/status",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            return {"id": request_id, "status": status}
        except Exception as exc:
            logger.error("BambooHR update_time_off_status error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_bamboohr_employee(employee_id: str) -> dict:
        """Terminate/deactivate a BambooHR employee record.

        This deactivates the employee account but preserves all historical
        data for audit and payroll purposes.

        Args:
            employee_id: BambooHR employee ID.

        Returns:
            dict confirming deactivation.
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.delete(f"{base}/employees/{employee_id}", timeout=20)
            resp.raise_for_status()
            return {"id": employee_id, "status": "deactivated"}
        except Exception as exc:
            logger.error("BambooHR delete_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_bamboohr_time_off(request_id: str) -> dict:
        """Cancel/delete a BambooHR time-off request.

        Args:
            request_id: Time-off request ID to cancel.

        Returns:
            dict confirming deletion/cancellation.
        """
        cfg = get_config().tools.get("bamboohr")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "BambooHR tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.delete(f"{base}/time_off/requests/{request_id}", timeout=20)
            resp.raise_for_status()
            return {"id": request_id, "status": "deleted"}
        except Exception as exc:
            logger.error("BambooHR delete_time_off error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_bamboohr_employees,
        get_bamboohr_employee,
        get_bamboohr_employee_fields,
        list_bamboohr_time_off_types,
        list_bamboohr_time_off_requests,
        get_bamboohr_who_is_out,
        # Create
        create_bamboohr_employee,
        request_bamboohr_time_off,
        # Update
        update_bamboohr_employee,
        update_bamboohr_time_off_status,
        # Delete
        delete_bamboohr_employee,
        delete_bamboohr_time_off,
    ]
