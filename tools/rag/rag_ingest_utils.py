"""Shared utilities for RAG document ingestion.

Combines two concerns:
  - Scope registry  : tracks RAG files by access scope (org, department, personal)
  - Document analysis: AI-powered metadata extraction via Gemini Flash

Registry JSON schema (stored in GCS):
{
  "org_files": ["projects/.../ragFiles/abc", ...],
  "dept_files": {
    "sales": ["projects/.../ragFiles/xyz", ...],
    ...
  },
  "personal_files": {
    "user@company.com": [
      {"rag_file_name": "projects/.../ragFiles/zzz", "display_name": "my_notes.txt"},
      ...
    ],
    ...
  }
}
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

KNOWN_DEPARTMENTS = [
    "sales", "engineering", "hr", "finance", "legal",
    "marketing", "operations", "executive", "product", "support",
]

# ---------------------------------------------------------------------------
# Scope registry
# ---------------------------------------------------------------------------

def _registry_read(uri: str) -> dict:
    if not uri:
        return {"org_files": [], "dept_files": {}}
    try:
        from tools.utils.gcs_utils import read_gcs_text
        return json.loads(read_gcs_text(uri))
    except Exception:
        return {"org_files": [], "dept_files": {}}


def _registry_write(data: dict, uri: str) -> None:
    if not uri:
        return
    try:
        from tools.utils.gcs_utils import write_gcs_text
        write_gcs_text(uri, json.dumps(data, indent=2))
    except Exception as exc:
        logger.error("scope_registry: write failed: %s", exc)


def register_org_file(file_name: str, registry_uri: str) -> None:
    """Mark a RAG file as accessible to the whole organisation."""
    data = _registry_read(registry_uri)
    org = data.setdefault("org_files", [])
    if file_name not in org:
        org.append(file_name)
    _registry_write(data, registry_uri)
    logger.info("scope_registry: org-registered %s", file_name)


def register_dept_files(file_name: str, departments: list[str], registry_uri: str) -> None:
    """Mark a RAG file as accessible to specific departments."""
    data = _registry_read(registry_uri)
    dept_map = data.setdefault("dept_files", {})
    for dept in departments:
        key = dept.lower().strip()
        bucket = dept_map.setdefault(key, [])
        if file_name not in bucket:
            bucket.append(file_name)
    _registry_write(data, registry_uri)
    logger.info("scope_registry: dept-registered %s → %s", file_name, departments)


def get_accessible_files(departments: list[str], registry_uri: str) -> list[str]:
    """Return all file names accessible to given department(s) plus org-wide files."""
    data = _registry_read(registry_uri)
    files: set[str] = set(data.get("org_files", []))
    dept_map = data.get("dept_files", {})
    for dept in departments:
        files.update(dept_map.get(dept.lower().strip(), []))
    return list(files)


def get_all_registry(registry_uri: str) -> dict:
    """Return the full registry dict (for admin use)."""
    return _registry_read(registry_uri)


def remove_file(file_name: str, registry_uri: str) -> None:
    """Remove a file from every scope bucket in the registry."""
    data = _registry_read(registry_uri)
    org = data.get("org_files", [])
    if file_name in org:
        org.remove(file_name)
    for bucket in data.get("dept_files", {}).values():
        if file_name in bucket:
            bucket.remove(file_name)
    _registry_write(data, registry_uri)
    logger.info("scope_registry: removed %s from all scopes", file_name)


# ---------------------------------------------------------------------------
# Personal-file registry  (per-user entries under "personal_files")
# ---------------------------------------------------------------------------

def register_personal_file(
    user_id: str,
    rag_file_resource_name: str,
    display_name: str,
    registry_uri: str,
) -> None:
    """Append a RAG file to user_id's personal section of the registry."""
    if not user_id or not rag_file_resource_name:
        return
    data = _registry_read(registry_uri)
    personal: dict = data.setdefault("personal_files", {})
    user_files: list = personal.setdefault(user_id, [])
    entry = {"rag_file_name": rag_file_resource_name, "display_name": display_name}
    if not any(f.get("rag_file_name") == rag_file_resource_name for f in user_files):
        user_files.append(entry)
    _registry_write(data, registry_uri)
    logger.info("scope_registry: personal-registered %s → user=%s", rag_file_resource_name, user_id)


def get_personal_file_names(user_id: str, registry_uri: str) -> list[str]:
    """Return the list of RAG file resource names owned by user_id."""
    data = _registry_read(registry_uri)
    user_files = data.get("personal_files", {}).get(user_id, [])
    return [f["rag_file_name"] for f in user_files if isinstance(f, dict) and f.get("rag_file_name")]


def list_personal_files(user_id: str, registry_uri: str) -> list[dict]:
    """Return full metadata entries for user_id's personal files."""
    data = _registry_read(registry_uri)
    return list(data.get("personal_files", {}).get(user_id, []))


def remove_personal_file(user_id: str, rag_file_resource_name: str, registry_uri: str) -> None:
    """Remove a specific file from user_id's personal section."""
    data = _registry_read(registry_uri)
    user_files = data.get("personal_files", {}).get(user_id, [])
    data["personal_files"][user_id] = [
        f for f in user_files
        if isinstance(f, dict) and f.get("rag_file_name") != rag_file_resource_name
    ]
    _registry_write(data, registry_uri)
    logger.info("scope_registry: personal-removed %s from user=%s", rag_file_resource_name, user_id)


# ---------------------------------------------------------------------------
# Document analysis
# ---------------------------------------------------------------------------

_SAMPLE_CHARS = 3000
_ANALYSIS_MODEL = "gemini-2.5-flash"
_NO_ANALYZE_EXTS = frozenset({".json", ".csv", ".sql"})

_ANALYSIS_PROMPT = """\
Analyze this document and return structured metadata. Return ONLY valid JSON, no markdown fences.

{{
  "doc_category": "<one of: contract, proposal, technical, hr_policy, financial, marketing, operations, legal, sales, product, other>",
  "doc_type": "<one of: sow, proposal, spec, readme, code, report, policy, meeting_notes, template, invoice, agreement, roadmap, presentation, guide, other>",
  "topic": "<2-4 word topic summary>",
  "keywords": "<up to 8 comma-separated lowercase keywords most relevant to the content>",
  "suggested_departments": "<comma-separated list from: sales,engineering,hr,finance,legal,marketing,operations,executive,product,support — pick the ones that genuinely need this document>",
  "suggested_scope": "<organization if broadly useful for the entire company, otherwise department>"
}}

Filename: {filename}
Content sample:
{sample}"""


def analyze_document(content: bytes, filename: str) -> dict[str, str]:
    """Return metadata dict extracted by Gemini, or {} on any failure.

    Keys returned (all optional): doc_category, doc_type, topic, keywords,
    suggested_departments, suggested_scope.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext in _NO_ANALYZE_EXTS:
        return {}

    sample = content[:_SAMPLE_CHARS].decode("utf-8", errors="ignore").strip()
    if len(sample) < 50:
        return {}

    try:
        from vertexai.generative_models import GenerationConfig, GenerativeModel

        model = GenerativeModel(_ANALYSIS_MODEL)
        response = model.generate_content(
            _ANALYSIS_PROMPT.format(filename=filename, sample=sample),
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=250,
                temperature=0.0,
            ),
        )
        parsed = json.loads(response.text)
        valid_keys = {
            "doc_category", "doc_type", "topic", "keywords",
            "suggested_departments", "suggested_scope",
        }
        return {
            k: str(v).strip()[:200]
            for k, v in parsed.items()
            if k in valid_keys and v
        }
    except Exception as exc:
        logger.debug("Document analysis skipped for %s: %s", filename, exc)
        return {}
