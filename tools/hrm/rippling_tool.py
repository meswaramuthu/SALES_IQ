"""Rippling tool — Rippling Platform REST API v1.

Required credentials (set in tools_config.json or env vars):
  api_key : Rippling API key (Settings → App Shop → API → Generate API Key)
            Requires Rippling Platform app with appropriate scope:
              employees:read, employees:write
              departments:read, groups:read

In tools_config.json, reference secrets as:
  "api_key": "env:RIPPLING_API_KEY"

Tools exported:
  READ
    list_rippling_employees    - list all employees
    get_rippling_employee      - get a single employee by ID
    search_rippling_employees  - search employees by name or email
    list_rippling_departments  - list all departments
    list_rippling_teams        - list all teams/groups
    get_rippling_company       - get company information
    list_rippling_roles        - list employee roles

  CREATE
    create_rippling_employee   - onboard a new employee

  UPDATE
    update_rippling_employee   - update employee fields
    update_rippling_department - update a department record

  DELETE
    terminate_rippling_employee - offboard/terminate an employee
    delete_rippling_department  - remove a department (if empty)
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)

_RIPPLING_BASE = "https://api.rippling.com/platform/api/v1"


def _session(cfg: dict):
    import requests
    sess = requests.Session()
    sess.headers.update({
        "Authorization": f"Bearer {cfg.get('api_key', '')}",
        "Content-Type": "application/json",
    })
    return sess


def get_tools() -> list[Callable]:

    # ── READ ──────────────────────────────────────────────────────────────────

    def list_rippling_employees(
        status: str = "ACTIVE",
        department_id: str = "",
        page: int = 0,
        page_size: int = 50,
    ) -> dict:
        """List employees in Rippling.

        Args:
            status: Employment status filter — 'ACTIVE' (default), 'TERMINATED',
                    'LEAVE_OF_ABSENCE', or blank for all.
            department_id: Filter by department ID. Leave blank for all departments.
            page: Zero-based page number (default 0).
            page_size: Employees per page (default 50, max 100).

        Returns:
            dict with list of employees (id, name, email, role, department, status).
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            params: dict = {"page": page, "pageSize": page_size}
            if status:
                params["employmentType"] = status
            if department_id:
                params["departmentId"] = department_id
            resp = sess.get(f"{_RIPPLING_BASE}/employees", params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            employees = [
                {
                    "id": e.get("id", ""),
                    "name": e.get("name", f"{e.get('firstName', '')} {e.get('lastName', '')}").strip(),
                    "email": e.get("workEmail", e.get("email", "")),
                    "role": e.get("roleState", {}).get("name", e.get("title", "")),
                    "department": e.get("department", {}).get("name", "") if isinstance(e.get("department"), dict) else e.get("department", ""),
                    "start_date": e.get("startDate", ""),
                    "employment_status": e.get("employmentStatus", ""),
                }
                for e in (data if isinstance(data, list) else data.get("data", []))
            ]
            return {"employees": employees, "count": len(employees)}
        except Exception as exc:
            logger.error("Rippling list_employees error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_rippling_employee(employee_id: str) -> dict:
        """Get a single Rippling employee by ID.

        Args:
            employee_id: Rippling employee ID.

        Returns:
            dict with full employee details.
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            resp = sess.get(f"{_RIPPLING_BASE}/employees/{employee_id}", timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Rippling get_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def search_rippling_employees(query: str, status: str = "ACTIVE") -> dict:
        """Search Rippling employees by name or email.

        Args:
            query: Name or email fragment to search.
            status: 'ACTIVE' (default), 'TERMINATED', or blank for all.

        Returns:
            dict with list of matching employees.
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            params: dict = {"search": query}
            if status:
                params["employmentType"] = status
            resp = sess.get(f"{_RIPPLING_BASE}/employees", params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            employees = [
                {
                    "id": e.get("id", ""),
                    "name": e.get("name", f"{e.get('firstName', '')} {e.get('lastName', '')}").strip(),
                    "email": e.get("workEmail", e.get("email", "")),
                    "role": e.get("title", ""),
                    "department": e.get("department", {}).get("name", "") if isinstance(e.get("department"), dict) else e.get("department", ""),
                }
                for e in (data if isinstance(data, list) else data.get("data", []))
            ]
            return {"employees": employees, "count": len(employees)}
        except Exception as exc:
            logger.error("Rippling search_employees error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_rippling_departments(page: int = 0, page_size: int = 50) -> dict:
        """List all departments in Rippling.

        Args:
            page: Zero-based page number (default 0).
            page_size: Departments per page (default 50).

        Returns:
            dict with list of departments (id, name, headCount).
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            resp = sess.get(
                f"{_RIPPLING_BASE}/departments",
                params={"page": page, "pageSize": page_size},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            departments = [
                {
                    "id": d.get("id", ""),
                    "name": d.get("name", ""),
                    "head_count": d.get("headCount", 0),
                    "manager_id": d.get("managerId", ""),
                }
                for d in (data if isinstance(data, list) else data.get("data", []))
            ]
            return {"departments": departments, "count": len(departments)}
        except Exception as exc:
            logger.error("Rippling list_departments error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_rippling_teams(page: int = 0, page_size: int = 50) -> dict:
        """List all teams/groups in Rippling.

        Args:
            page: Zero-based page number (default 0).
            page_size: Teams per page (default 50).

        Returns:
            dict with list of teams (id, name, memberCount).
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            resp = sess.get(
                f"{_RIPPLING_BASE}/groups",
                params={"page": page, "pageSize": page_size},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            teams = [
                {
                    "id": t.get("id", ""),
                    "name": t.get("name", ""),
                    "member_count": t.get("memberCount", 0),
                    "type": t.get("type", ""),
                }
                for t in (data if isinstance(data, list) else data.get("data", []))
            ]
            return {"teams": teams, "count": len(teams)}
        except Exception as exc:
            logger.error("Rippling list_teams error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_rippling_company() -> dict:
        """Get company information from Rippling.

        Returns:
            dict with company name, EIN, address, and size.
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            resp = sess.get(f"{_RIPPLING_BASE}/companies/current", timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Rippling get_company error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def list_rippling_roles(page: int = 0, page_size: int = 50) -> dict:
        """List employee roles in Rippling.

        Args:
            page: Zero-based page number (default 0).
            page_size: Roles per page (default 50).

        Returns:
            dict with list of roles (id, name).
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            resp = sess.get(
                f"{_RIPPLING_BASE}/roles",
                params={"page": page, "pageSize": page_size},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            roles = [
                {"id": r.get("id", ""), "name": r.get("name", "")}
                for r in (data if isinstance(data, list) else data.get("data", []))
            ]
            return {"roles": roles, "count": len(roles)}
        except Exception as exc:
            logger.error("Rippling list_roles error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_rippling_employee(
        first_name: str,
        last_name: str,
        work_email: str,
        start_date: str,
        department_id: str = "",
        title: str = "",
        manager_id: str = "",
        employment_type: str = "FULL_TIME",
    ) -> dict:
        """Onboard a new employee in Rippling.

        Args:
            first_name: Employee first name.
            last_name: Employee last name.
            work_email: Work email address.
            start_date: Employment start date in YYYY-MM-DD format.
            department_id: Department ID (from list_rippling_departments). Optional.
            title: Job title. Optional.
            manager_id: Manager's Rippling employee ID. Optional.
            employment_type: 'FULL_TIME' (default), 'PART_TIME', or 'CONTRACTOR'.

        Returns:
            dict with created employee ID.
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            payload: dict = {
                "firstName": first_name,
                "lastName": last_name,
                "workEmail": work_email,
                "startDate": start_date,
                "employmentType": employment_type,
            }
            if department_id:
                payload["departmentId"] = department_id
            if title:
                payload["title"] = title
            if manager_id:
                payload["managerId"] = manager_id
            resp = sess.post(f"{_RIPPLING_BASE}/employees", json=payload, timeout=20)
            resp.raise_for_status()
            result = resp.json()
            employee_id = result.get("id", "") if isinstance(result, dict) else ""
            return {"id": employee_id, "status": "created"}
        except Exception as exc:
            logger.error("Rippling create_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_rippling_employee(employee_id: str, fields: dict) -> dict:
        """Update fields of a Rippling employee record.

        Args:
            employee_id: Rippling employee ID.
            fields: Dict of fields to update. Common fields:
                    title, departmentId, managerId, workEmail,
                    workPhone, startDate, employmentType.

        Returns:
            dict with employee_id and status.
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            resp = sess.patch(f"{_RIPPLING_BASE}/employees/{employee_id}", json=fields, timeout=20)
            resp.raise_for_status()
            return {"id": employee_id, "status": "updated"}
        except Exception as exc:
            logger.error("Rippling update_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def update_rippling_department(department_id: str, fields: dict) -> dict:
        """Update a Rippling department.

        Args:
            department_id: Rippling department ID.
            fields: Dict of fields to update (name, managerId, etc.).

        Returns:
            dict with department_id and status.
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            resp = sess.patch(f"{_RIPPLING_BASE}/departments/{department_id}", json=fields, timeout=20)
            resp.raise_for_status()
            return {"id": department_id, "status": "updated"}
        except Exception as exc:
            logger.error("Rippling update_department error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ── DELETE ────────────────────────────────────────────────────────────────

    def terminate_rippling_employee(
        employee_id: str,
        termination_date: str,
        termination_reason: str = "voluntary",
        regrettable: bool = False,
    ) -> dict:
        """Offboard/terminate a Rippling employee.

        This initiates the Rippling offboarding workflow including
        system access revocation, payroll cutoff, and equipment collection.

        Args:
            employee_id: Rippling employee ID.
            termination_date: Last day of employment in YYYY-MM-DD format.
            termination_reason: Reason code — 'voluntary', 'involuntary',
                                'retirement', 'contract_end'. Default 'voluntary'.
            regrettable: Mark as regrettable departure. Default False.

        Returns:
            dict with employee_id and offboarding status.
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            payload: dict = {
                "terminationDate": termination_date,
                "terminationReason": termination_reason,
                "regrettable": regrettable,
            }
            resp = sess.post(f"{_RIPPLING_BASE}/employees/{employee_id}/terminate", json=payload, timeout=20)
            resp.raise_for_status()
            return {
                "id": employee_id,
                "termination_date": termination_date,
                "status": "terminated",
            }
        except Exception as exc:
            logger.error("Rippling terminate_employee error: %s", exc)
            return {"status": "error", "message": str(exc)}

    def delete_rippling_department(department_id: str) -> dict:
        """Remove a department from Rippling (only if empty — no members).

        Args:
            department_id: Rippling department ID.

        Returns:
            dict confirming deletion.
        """
        cfg = get_config().tools.get("rippling")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Rippling tool is currently disabled."}
        try:
            sess = _session(cfg.config)
            resp = sess.delete(f"{_RIPPLING_BASE}/departments/{department_id}", timeout=20)
            resp.raise_for_status()
            return {"id": department_id, "status": "deleted"}
        except Exception as exc:
            logger.error("Rippling delete_department error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        # Read
        list_rippling_employees,
        get_rippling_employee,
        search_rippling_employees,
        list_rippling_departments,
        list_rippling_teams,
        get_rippling_company,
        list_rippling_roles,
        # Create
        create_rippling_employee,
        # Update
        update_rippling_employee,
        update_rippling_department,
        # Delete
        terminate_rippling_employee,
        delete_rippling_department,
    ]
