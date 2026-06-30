"""Accessibility scope registry for the document-mining agent.

Tracks which RAG files are accessible org-wide vs per-department.
Stored as JSON in GCS at the URI configured under `scope_registry_uri`.

Registry JSON schema:
{
  "org_files": ["projects/.../ragFiles/abc", ...],
  "dept_files": {
    "sales": ["projects/.../ragFiles/xyz", ...],
    "engineering": [...],
    ...
  }
}

Public API:
  register_org_file(file_name, registry_uri)
  register_dept_files(file_name, departments, registry_uri)
  get_accessible_files(departments, registry_uri) -> list[str]
  get_all_registry(registry_uri) -> dict
  remove_file(file_name, registry_uri)
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

KNOWN_DEPARTMENTS = [
    "sales", "engineering", "hr", "finance", "legal",
    "marketing", "operations", "executive", "product", "support",
]


def _read(uri: str) -> dict:
    if not uri:
        return {"org_files": [], "dept_files": {}}
    try:
        from tools.utils.gcs_utils import read_gcs_text
        return json.loads(read_gcs_text(uri))
    except Exception:
        return {"org_files": [], "dept_files": {}}


def _write(data: dict, uri: str) -> None:
    if not uri:
        return
    try:
        from tools.utils.gcs_utils import write_gcs_text
        write_gcs_text(uri, json.dumps(data, indent=2))
    except Exception as exc:
        logger.error("scope_registry: write failed: %s", exc)


def register_org_file(file_name: str, registry_uri: str) -> None:
    """Mark a RAG file as accessible to the whole organisation."""
    data = _read(registry_uri)
    org = data.setdefault("org_files", [])
    if file_name not in org:
        org.append(file_name)
    _write(data, registry_uri)
    logger.info("scope_registry: org-registered %s", file_name)


def register_dept_files(file_name: str, departments: list[str], registry_uri: str) -> None:
    """Mark a RAG file as accessible to specific departments."""
    data = _read(registry_uri)
    dept_map = data.setdefault("dept_files", {})
    for dept in departments:
        key = dept.lower().strip()
        bucket = dept_map.setdefault(key, [])
        if file_name not in bucket:
            bucket.append(file_name)
    _write(data, registry_uri)
    logger.info("scope_registry: dept-registered %s → %s", file_name, departments)


def get_accessible_files(departments: list[str], registry_uri: str) -> list[str]:
    """Return all file names accessible to given department(s) plus org-wide files."""
    data = _read(registry_uri)
    files: set[str] = set(data.get("org_files", []))
    dept_map = data.get("dept_files", {})
    for dept in departments:
        files.update(dept_map.get(dept.lower().strip(), []))
    return list(files)


def get_all_registry(registry_uri: str) -> dict:
    """Return the full registry dict (for admin use)."""
    return _read(registry_uri)


def remove_file(file_name: str, registry_uri: str) -> None:
    """Remove a file from every scope bucket in the registry."""
    data = _read(registry_uri)
    org = data.get("org_files", [])
    if file_name in org:
        org.remove(file_name)
    for bucket in data.get("dept_files", {}).values():
        if file_name in bucket:
            bucket.remove(file_name)
    _write(data, registry_uri)
    logger.info("scope_registry: removed %s from all scopes", file_name)
