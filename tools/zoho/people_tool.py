"""Zoho People tool — Zoho People REST API v2.

Required credentials (set in tools_config.json):
  client_id     : Zoho OAuth2 client ID
  client_secret : Zoho OAuth2 client secret
  refresh_token : Zoho OAuth2 refresh token (permanent — never needs rotation)
  base_url      : Data centre base URL (default https://people.zoho.com)
                    EU: https://people.zoho.eu
                    IN: https://people.zoho.in
  accounts_url  : (optional) Zoho accounts domain for token refresh

In tools_config.json, reference secrets as:
  "client_id":     "env:ZOHO_CLIENT_ID"
  "client_secret": "env:ZOHO_CLIENT_SECRET"
  "refresh_token": "env:ZOHO_REFRESH_TOKEN"

The access token is fetched and cached automatically; it never needs to be
stored or rotated manually.

Tools exported:
  READ
    list_zoho_people_employees    - list all employees
    get_zoho_people_employee      - get a single employee record
    search_zoho_people_employees  - search employees by name or email
    list_zoho_people_departments  - list all departments
    list_zoho_people_leave_types  - list configured leave types
    get_zoho_people_leave_balance - get leave balance for an employee

  CREATE
    create_zoho_people_employee   - add a new employee record
    apply_zoho_people_leave       - submit a leave application for an employee

  UPDATE
    update_zoho_people_employee   - update employee fields
    approve_zoho_people_leave     - approve or reject a leave application

  DELETE
    delete_zoho_people_employee   - terminate/delete an employee record
    cancel_zoho_people_leave      - cancel a submitted leave application
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
    base = cfg.get("base_url", "https://people.zoho.com").rstrip("/")
    return sess, base


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_zoho_people_employees(limit: int = 50, page: int = 1) -> dict:
        """List all employees in Zoho People.

        Args:
            limit: Number of employees to return (default 50, max 200).
            page: Page number for pagination (default 1).

        Returns:
            dict with list of employees (id, name, email, department, designation, status).
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            params = {"sIndex": (page - 1) * limit + 1, "limit": limit}
            resp = sess.get(f"{base}/people/api/forms/employee/getrecords", params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            records = data.get("response", {}).get("result", [])
            employees = []
            for r in records:
                emp = r if isinstance(r, dict) else {}
                employees.append({
                    "id": emp.get("Zoho_ID", emp.get("EmployeeID", "")),
                    "name": emp.get("EmployeeName", emp.get("First_Name", "") + " " + emp.get("Last_Name", "")),
                    "email": emp.get("EmailID", ""),
                    "department": emp.get("Department", ""),
                    "designation": emp.get("Designation", ""),
                    "employment_type": emp.get("EmploymentType", ""),
                    "status": emp.get("Employeestatus", "Active"),
                })
            return {"employees": employees, "count": len(employees)}
        except Exception as exc:
            logger.error("Zoho People list_employees error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_zoho_people_employee(employee_id: str) -> dict:
        """Get a single Zoho People employee record by ID.

        Args:
            employee_id: Zoho People employee ID (Zoho_ID or EmployeeID).

        Returns:
            dict with full employee details.
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(
                f"{base}/people/api/forms/employee/getrecords",
                params={"searchColumn": "Zoho_ID", "searchValue": employee_id},
                timeout=20,
            )
            resp.raise_for_status()
            records = resp.json().get("response", {}).get("result", [])
            if not records:
                return {"status": "not_found", "message": f"Employee {employee_id} not found."}
            return records[0] if isinstance(records[0], dict) else {}
        except Exception as exc:
            logger.error("Zoho People get_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def search_zoho_people_employees(query: str) -> dict:
        """Search Zoho People employees by name or email.

        Args:
            query: Name or email fragment to search.

        Returns:
            dict with list of matching employees.
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(
                f"{base}/people/api/forms/employee/getrecords",
                params={"searchColumn": "EmployeeName", "searchValue": query},
                timeout=20,
            )
            resp.raise_for_status()
            records = resp.json().get("response", {}).get("result", [])
            employees = [
                {
                    "id": r.get("Zoho_ID", ""),
                    "name": r.get("EmployeeName", ""),
                    "email": r.get("EmailID", ""),
                    "department": r.get("Department", ""),
                    "designation": r.get("Designation", ""),
                }
                for r in records
                if isinstance(r, dict)
            ]
            return {"employees": employees, "count": len(employees)}
        except Exception as exc:
            logger.error("Zoho People search_employees error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zoho_people_departments() -> dict:
        """List all departments configured in Zoho People.

        Returns:
            dict with list of departments (id, name).
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/people/api/org/departments", timeout=20)
            resp.raise_for_status()
            depts = resp.json().get("response", {}).get("result", [])
            departments = [
                {"id": d.get("departmentId", ""), "name": d.get("departmentName", "")}
                for d in depts
                if isinstance(d, dict)
            ]
            return {"departments": departments, "count": len(departments)}
        except Exception as exc:
            logger.error("Zoho People list_departments error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_zoho_people_leave_types() -> dict:
        """List all leave types configured in Zoho People.

        Returns:
            dict with list of leave types (id, name, unit, isHalfDayLeave).
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(f"{base}/people/api/leave/getLeaveTypeDetails", timeout=20)
            resp.raise_for_status()
            leave_types = [
                {
                    "id": lt.get("leaveTypeId", lt.get("sysRef", "")),
                    "name": lt.get("Name", lt.get("leaveTypeName", "")),
                    "unit": lt.get("unit", "days"),
                    "is_half_day": lt.get("isHalfDayLeave", False),
                }
                for lt in resp.json().get("response", {}).get("result", [])
                if isinstance(lt, dict)
            ]
            return {"leave_types": leave_types, "count": len(leave_types)}
        except Exception as exc:
            logger.error("Zoho People list_leave_types error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_zoho_people_leave_balance(employee_id: str) -> dict:
        """Get leave balance for a Zoho People employee.

        Args:
            employee_id: Zoho People employee ID.

        Returns:
            dict with leave balance per leave type.
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.get(
                f"{base}/people/api/leave/getLeaveInfoOfUser",
                params={"userId": employee_id},
                timeout=20,
            )
            resp.raise_for_status()
            result = resp.json().get("response", {}).get("result", [])
            balances = [
                {
                    "leave_type": lb.get("displayName", ""),
                    "total": lb.get("totalDays", lb.get("total", 0)),
                    "used": lb.get("usedDays", lb.get("used", 0)),
                    "balance": lb.get("balanceDays", lb.get("balance", 0)),
                }
                for lb in result
                if isinstance(lb, dict)
            ]
            return {"employee_id": employee_id, "leave_balances": balances}
        except Exception as exc:
            logger.error("Zoho People get_leave_balance error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_zoho_people_employee(
        first_name: str,
        last_name: str,
        email: str,
        department: str = "",
        designation: str = "",
        date_of_joining: str = "",
        employment_type: str = "Permanent",
    ) -> dict:
        """Create a new employee record in Zoho People.

        Args:
            first_name: Employee first name.
            last_name: Employee last name.
            email: Work email address.
            department: Department name.
            designation: Job title / designation.
            date_of_joining: Joining date in YYYY-MM-DD format.
            employment_type: 'Permanent' (default), 'Contract', 'Intern', 'Part-Time'.

        Returns:
            dict with created employee ID.
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {
                "First_Name": first_name,
                "Last_Name": last_name,
                "EmailID": email,
                "EmploymentType": employment_type,
            }
            if department:
                payload["Department"] = department
            if designation:
                payload["Designation"] = designation
            if date_of_joining:
                payload["Dateofjoining"] = date_of_joining
            resp = sess.post(
                f"{base}/people/api/forms/employee/insertrecord",
                data=payload,
                timeout=20,
            )
            resp.raise_for_status()
            result = resp.json().get("response", {})
            return {
                "id": result.get("result", {}).get("pkId", ""),
                "status": "created",
            }
        except Exception as exc:
            logger.error("Zoho People create_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def apply_zoho_people_leave(
        employee_id: str,
        leave_type_id: str,
        from_date: str,
        to_date: str,
        reason: str = "",
    ) -> dict:
        """Submit a leave application for a Zoho People employee.

        Args:
            employee_id: Zoho People employee ID.
            leave_type_id: Leave type ID (from list_zoho_people_leave_types).
            from_date: Leave start date in YYYY-MM-DD format.
            to_date: Leave end date in YYYY-MM-DD format.
            reason: Reason for leave.

        Returns:
            dict with leave request ID and status.
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload = {
                "userId": employee_id,
                "leaveTypeId": leave_type_id,
                "from": from_date,
                "to": to_date,
                "reason": reason,
            }
            resp = sess.post(f"{base}/people/api/leave/applyLeave", data=payload, timeout=20)
            resp.raise_for_status()
            result = resp.json().get("response", {})
            return {
                "id": result.get("result", {}).get("requestId", ""),
                "status": "applied",
            }
        except Exception as exc:
            logger.error("Zoho People apply_leave error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_zoho_people_employee(employee_id: str, fields: dict) -> dict:
        """Update fields of a Zoho People employee record.

        Args:
            employee_id: Zoho People employee ID.
            fields: Dict of Zoho People field names → new values.
                    Common fields: Department, Designation, EmailID,
                    MobilePhone, WorkPhone, Employeestatus.

        Returns:
            dict with employee_id and status.
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload = {**fields, "Zoho_ID": employee_id}
            resp = sess.post(
                f"{base}/people/api/forms/employee/updaterecord",
                data=payload,
                timeout=20,
            )
            resp.raise_for_status()
            return {"id": employee_id, "status": "updated"}
        except Exception as exc:
            logger.error("Zoho People update_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def approve_zoho_people_leave(request_id: str, action: str = "approve", reason: str = "") -> dict:
        """Approve or reject a Zoho People leave application.

        Args:
            request_id: Leave request ID (from apply_zoho_people_leave).
            action: 'approve' (default) or 'reject'.
            reason: Reason for rejection (required when action='reject').

        Returns:
            dict with request_id and outcome status.
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {"requestId": request_id, "action": action}
            if reason:
                payload["reason"] = reason
            resp = sess.post(f"{base}/people/api/leave/updateLeaveStatus", json=payload, timeout=20)
            resp.raise_for_status()
            return {"id": request_id, "status": action + "d"}
        except Exception as exc:
            logger.error("Zoho People approve_leave error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_zoho_people_employee(employee_id: str) -> dict:
        """Terminate/delete a Zoho People employee record.

        WARNING: This marks the employee as terminated. Ensure HR processes
        are followed before calling this tool.

        Args:
            employee_id: Zoho People employee ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            resp = sess.delete(
                f"{base}/people/api/forms/employee/deleterecord",
                params={"id": employee_id},
                timeout=20,
            )
            resp.raise_for_status()
            return {"id": employee_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Zoho People delete_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def cancel_zoho_people_leave(request_id: str, reason: str = "") -> dict:
        """Cancel a submitted Zoho People leave application.

        Args:
            request_id: Leave request ID to cancel.
            reason: Optional reason for cancellation.

        Returns:
            dict confirming cancellation.
        """
        cfg = get_config().tools.get("zoho_people")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Zoho People tool is currently disabled."}
        try:
            sess, base = _session(cfg.config)
            payload: dict = {"requestId": request_id, "action": "cancel"}
            if reason:
                payload["reason"] = reason
            resp = sess.post(f"{base}/people/api/leave/updateLeaveStatus", json=payload, timeout=20)
            resp.raise_for_status()
            return {"id": request_id, "status": "cancelled"}
        except Exception as exc:
            logger.error("Zoho People cancel_leave error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_zoho_people_employees,
        get_zoho_people_employee,
        search_zoho_people_employees,
        list_zoho_people_departments,
        list_zoho_people_leave_types,
        get_zoho_people_leave_balance,
        # Create
        create_zoho_people_employee,
        apply_zoho_people_leave,
        # Update
        update_zoho_people_employee,
        approve_zoho_people_leave,
        # Delete
        delete_zoho_people_employee,
        cancel_zoho_people_leave,
    ]
