"""Document-mining agent tool implementations.

Tools exposed by this module:
  analyze_document_content          — AI analysis: category, type, keywords, suggested scope
  upload_document_to_knowledge_base — Upload with full metadata tagging + scope registration
  list_knowledge_base_documents     — List docs with scope/department/agent filters

Metadata tags applied to every RAG file:
  source_agent        — agent or system that originated the upload request
  doc_category        — high-level category (contract, financial, technical, …)
  doc_type            — fine-grained type (sow, invoice, spec, report, …)
  topic               — 2-4 word summary
  keywords            — comma-separated keywords
  accessibility_scope — "organization" or "department"
  departments         — comma-separated department names (when scope=department)
  uploaded_by         — authenticated user ID / email
  uploaded_at         — ISO-8601 UTC timestamp
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 50 * 1024 * 1024

_RAG_EXTS = frozenset({
    ".pdf", ".docx", ".pptx", ".txt", ".md", ".rst",
    ".html", ".htm", ".json", ".py", ".sql",
    ".xlsx", ".csv", ".jpeg", ".jpg",
})

_DRIVE_URL_RE = re.compile(r"https://drive\.google\.com/")

_DEFAULT_SCOPE_REGISTRY_URI = "gs://stratova-platform/knowledge-iq/scope_file_registry.json"

AVAILABLE_DEPARTMENTS = [
    "sales", "engineering", "hr", "finance", "legal",
    "marketing", "operations", "executive", "product", "support",
]


def build_dm_tools(config_getter: Callable) -> list[Callable]:
    """Return all document-mining tool functions, wired to config_getter."""

    def _init_vertexai(corpus_or_file: str) -> None:
        import vertexai
        from google.cloud.aiplatform import initializer

        m = re.search(r"projects/([^/]+)/locations/([^/]+)/", corpus_or_file)
        if not m:
            return
        project, location = m.group(1), m.group(2)
        if getattr(initializer.global_config, "location", None) != location:
            vertexai.init(project=project, location=location)

    def _user_id(tool_context) -> str:
        uid = getattr(tool_context, "user_id", None) or ""
        return uid.strip() or "anonymous"

    # ------------------------------------------------------------------ #
    # TOOL 1: ANALYZE                                                      #
    # ------------------------------------------------------------------ #

    def analyze_document_content(
        content_sample: str,
        filename: str = "document.txt",
        tool_context=None,
    ) -> dict:
        """Analyze a document to extract AI-suggested metadata and accessibility scope.

        ALWAYS call this BEFORE upload_document_to_knowledge_base.
        Present the analysis summary to the user and ask them to confirm or
        adjust the accessibility scope and departments.

        Workflow:
          1. Call this tool with the first ~3 000 characters of the document text.
          2. Show the user: document type, topic, keywords, suggested scope.
          3. Ask: "Should this be accessible to the whole organisation, or only
             specific departments?"
          4. If department scope — ask which departments (see AVAILABLE_DEPARTMENTS).
          5. Call upload_document_to_knowledge_base with the confirmed metadata.

        Args:
            content_sample: First portion of document text (up to 3 000 chars).
            filename: Original filename — used to infer type from extension.

        Returns:
            dict with: doc_category, doc_type, topic, keywords,
            suggested_departments (list), suggested_scope, analysis_summary (str).
        """
        if not content_sample or not content_sample.strip():
            return {"status": "error", "message": "No content provided for analysis."}

        try:
            from document_analysis import analyze_document

            result = analyze_document(
                content_sample.encode("utf-8", errors="ignore"),
                filename or "document.txt",
            )

            doc_type = result.get("doc_type", "other")
            doc_category = result.get("doc_category", "other")
            topic = result.get("topic", "")
            keywords = result.get("keywords", "")
            suggested_departments_raw = result.get("suggested_departments", "")
            suggested_scope = result.get("suggested_scope", "organization")

            dept_list = [
                d.strip() for d in suggested_departments_raw.split(",")
                if d.strip()
            ]

            summary_lines = [
                f"**Document type:** {doc_type} ({doc_category})",
            ]
            if topic:
                summary_lines.append(f"**Topic:** {topic}")
            if keywords:
                summary_lines.append(f"**Keywords:** {keywords}")
            summary_lines.append(f"\n**Suggested accessibility:** {suggested_scope.upper()}")
            if dept_list and suggested_scope == "department":
                summary_lines.append(f"**Suggested departments:** {', '.join(dept_list)}")
            summary_lines.append(
                f"\n**Available departments:** {', '.join(AVAILABLE_DEPARTMENTS)}"
            )

            return {
                "status": "success",
                "doc_category": doc_category,
                "doc_type": doc_type,
                "topic": topic,
                "keywords": keywords,
                "suggested_departments": dept_list,
                "suggested_scope": suggested_scope,
                "analysis_summary": "\n".join(summary_lines),
            }
        except Exception as exc:
            logger.error("analyze_document_content error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------ #
    # TOOL 2: UPLOAD                                                       #
    # ------------------------------------------------------------------ #

    def upload_document_to_knowledge_base(
        display_name: str,
        extracted_text: str = "",
        source: str = "",
        source_agent: str = "user",
        doc_category: str = "",
        doc_type: str = "",
        topic: str = "",
        keywords: str = "",
        accessibility_scope: str = "organization",
        departments: str = "",
        tool_context=None,
    ) -> dict:
        """Upload a document to the knowledge base with full metadata tagging.

        IMPORTANT — follow this workflow in order:
          1. Call analyze_document_content() first.
          2. Present analysis to the user; ask them to confirm:
             a. Scope: "organization" (whole company) or "department" (restricted).
             b. If "department": which departments? (sales, engineering, hr, finance,
                legal, marketing, operations, executive, product, support)
          3. Call this tool with the confirmed values.

        The source_agent tag records which agent or system originated the upload
        (e.g. "crm_agent", "web_scraper_agent", "user") so documents can be
        filtered by their origin later.

        Args:
            display_name: Friendly document name shown in search results.
            extracted_text: Full document text (use for inline / attachment uploads).
            source: Google Drive URL or GCS URI (alternative to extracted_text).
            source_agent: Agent / system that triggered this upload.
            doc_category: High-level category (from analysis or user override).
            doc_type: Fine-grained type (from analysis or user override).
            topic: 2-4 word topic summary.
            keywords: Comma-separated keywords.
            accessibility_scope: "organization" (default) or "department".
            departments: Comma-separated dept names when scope is "department".

        Returns:
            dict with: status, rag_file_name, accessibility_scope, departments,
            tags_applied, message.
        """
        cfg = config_getter().tools.get("rag")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Knowledge base is currently disabled."}
        if tool_context is None:
            return {"status": "error", "message": "No tool context available."}

        user_id = _user_id(tool_context)
        corpus = cfg.config.get("corpus", "")
        scope_registry_uri = cfg.config.get("scope_registry_uri", _DEFAULT_SCOPE_REGISTRY_URI)

        if not corpus:
            return {"status": "error", "message": "RAG corpus is not configured."}
        if not display_name:
            return {"status": "error", "message": "display_name is required."}
        if not extracted_text and not source:
            return {
                "status": "error",
                "message": "Provide either extracted_text (inline) or source (Drive URL / GCS URI).",
            }

        # Normalise scope
        scope = accessibility_scope.lower().strip()
        if scope not in ("organization", "department"):
            scope = "organization"

        dept_list: list[str] = []
        if scope == "department" and departments:
            dept_list = [d.lower().strip() for d in departments.split(",") if d.strip()]
            if not dept_list:
                return {
                    "status": "error",
                    "message": (
                        "scope is 'department' but no departments specified. "
                        f"Available: {', '.join(AVAILABLE_DEPARTMENTS)}"
                    ),
                }

        now_iso = datetime.now(timezone.utc).isoformat()
        user_metadata: dict[str, str] = {
            "source_agent": (source_agent or "user")[:100],
            "accessibility_scope": scope,
            "uploaded_by": user_id[:200],
            "uploaded_at": now_iso,
        }
        if doc_category:
            user_metadata["doc_category"] = doc_category[:100]
        if doc_type:
            user_metadata["doc_type"] = doc_type[:100]
        if topic:
            user_metadata["topic"] = topic[:200]
        if keywords:
            user_metadata["keywords"] = keywords[:500]
        if dept_list:
            user_metadata["departments"] = ",".join(dept_list)

        desc = f"[{scope.upper()}] {doc_category or 'document'} | uploaded by {user_id}"

        try:
            from vertexai.preview import rag

            _init_vertexai(corpus)

            # ---- Path A: inline extracted text ----
            if extracted_text and extracted_text.strip():
                chosen_name = display_name
                ext = os.path.splitext(chosen_name)[1].lower()
                if ext not in _RAG_EXTS:
                    chosen_name += ".txt"
                    ext = ".txt"

                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(extracted_text.encode("utf-8"))
                    tmp_path = tmp.name

                try:
                    rag_file = rag.upload_file(
                        corpus_name=corpus,
                        path=tmp_path,
                        display_name=chosen_name[:1000],
                        description=desc[:500],
                        **({"metadata": user_metadata} if user_metadata else {}),
                    )
                finally:
                    os.unlink(tmp_path)

                rag_file_name = rag_file.name
                _register(rag_file_name, scope, dept_list, scope_registry_uri)
                logger.info(
                    "dm_tools: uploaded %s scope=%s depts=%s agent=%s user=%s",
                    rag_file_name, scope, dept_list, source_agent, user_id,
                )
                return _success_response(
                    display_name, rag_file_name,
                    rag_file.display_name, scope, dept_list,
                    doc_category, doc_type, user_metadata,
                )

            # ---- Path B: Drive URL or GCS URI ----
            is_gcs = source.startswith("gs://")
            is_drive = bool(_DRIVE_URL_RE.match(source))
            if not (is_gcs or is_drive):
                return {
                    "status": "error",
                    "message": (
                        "Invalid source format. Accepted:\n"
                        "  - Google Drive: https://drive.google.com/file/d/…\n"
                        "  - GCS URI:      gs://bucket/path/to/file"
                    ),
                }

            before: set[str] = {f.name for f in rag.list_files(corpus_name=corpus)}
            rag.import_files(
                corpus_name=corpus,
                paths=[source],
                chunk_size=cfg.config.get("chunk_size", 512),
                chunk_overlap=cfg.config.get("chunk_overlap", 100),
            )
            after: set[str] = {f.name for f in rag.list_files(corpus_name=corpus)}
            new_names = list(after - before)

            if not new_names:
                return {
                    "status": "error",
                    "message": "No files were imported. Check the URL/URI and access permissions.",
                }

            for fn in new_names:
                _register(fn, scope, dept_list, scope_registry_uri)

            logger.info(
                "dm_tools: imported %d file(s) from %s scope=%s depts=%s agent=%s user=%s",
                len(new_names), source, scope, dept_list, source_agent, user_id,
            )
            return {
                "status": "success",
                "imported_count": len(new_names),
                "rag_file_names": new_names,
                "accessibility_scope": scope,
                "departments": dept_list if scope == "department" else [],
                "tags_applied": user_metadata,
                "message": (
                    f"Imported {len(new_names)} document(s) from source.\n"
                    f"Accessibility: {scope.upper()}"
                    + (f" → {', '.join(dept_list)}" if dept_list else "")
                ),
            }

        except TypeError:
            # Older SDK version without metadata kwarg — retry without it
            logger.warning("dm_tools: SDK lacks metadata kwarg — uploading without tags")
            return _upload_no_metadata(
                extracted_text, display_name, corpus, scope,
                dept_list, scope_registry_uri, user_metadata, _init_vertexai,
            )

        except Exception as exc:
            logger.error("upload_document_to_knowledge_base error: %s", exc)
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------ #
    # TOOL 3: LIST                                                          #
    # ------------------------------------------------------------------ #

    def list_knowledge_base_documents(
        filter_scope: str = "",
        filter_department: str = "",
        filter_source_agent: str = "",
        tool_context=None,
    ) -> dict:
        """List documents in the knowledge base with optional filters.

        Args:
            filter_scope: "organization" or "department" (empty = all).
            filter_department: Department name to filter by (e.g. "sales").
            filter_source_agent: Source agent name to filter by (e.g. "crm_agent").

        Returns:
            dict with: documents (list), count.
            Each document has: name, display_name, accessibility_scope,
            departments, create_time.
        """
        cfg = config_getter().tools.get("rag")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Knowledge base is currently disabled."}

        corpus = cfg.config.get("corpus", "")
        scope_registry_uri = cfg.config.get("scope_registry_uri", _DEFAULT_SCOPE_REGISTRY_URI)
        if not corpus:
            return {"status": "error", "message": "RAG corpus is not configured."}

        try:
            from scope_registry import get_all_registry
            from vertexai.preview import rag

            _init_vertexai(corpus)
            registry = get_all_registry(scope_registry_uri)

            # Build fast lookup: rag_file_name → (scope, dept_list)
            file_scope: dict[str, str] = {}
            file_depts: dict[str, list[str]] = {}

            for fn in registry.get("org_files", []):
                file_scope[fn] = "organization"
                file_depts[fn] = []

            for dept, fns in registry.get("dept_files", {}).items():
                for fn in fns:
                    if fn not in file_scope:
                        file_scope[fn] = "department"
                    file_depts.setdefault(fn, []).append(dept)

            results = []
            for f in rag.list_files(corpus_name=corpus):
                scope = file_scope.get(f.name, "unknown")
                depts = file_depts.get(f.name, [])

                if filter_scope and scope != filter_scope:
                    continue
                if filter_department and filter_department.lower() not in depts:
                    continue

                entry = {
                    "name": f.name,
                    "display_name": f.display_name,
                    "accessibility_scope": scope,
                    "departments": depts,
                    "create_time": str(getattr(f, "create_time", "")),
                }
                results.append(entry)

            return {"documents": results, "count": len(results)}

        except Exception as exc:
            logger.error("list_knowledge_base_documents error: %s", exc)
            return {"status": "error", "message": str(exc)}

    return [
        analyze_document_content,
        upload_document_to_knowledge_base,
        list_knowledge_base_documents,
    ]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _register(
    file_name: str,
    scope: str,
    dept_list: list[str],
    scope_registry_uri: str,
) -> None:
    if scope == "organization":
        from scope_registry import register_org_file
        register_org_file(file_name, scope_registry_uri)
    else:
        from scope_registry import register_dept_files
        register_dept_files(file_name, dept_list, scope_registry_uri)


def _success_response(
    display_name: str,
    rag_file_name: str,
    rag_display: str,
    scope: str,
    dept_list: list[str],
    doc_category: str,
    doc_type: str,
    tags: dict,
) -> dict:
    return {
        "status": "success",
        "rag_file_name": rag_file_name,
        "display_name": rag_display,
        "accessibility_scope": scope,
        "departments": dept_list if scope == "department" else [],
        "tags_applied": tags,
        "message": (
            f"'{display_name}' has been uploaded to the knowledge base.\n"
            f"Accessibility: {scope.upper()}"
            + (f" → {', '.join(dept_list)}" if dept_list else "")
            + f"\nCategory: {doc_category or 'unclassified'} | Type: {doc_type or 'other'}"
        ),
    }


def _upload_no_metadata(
    extracted_text: str,
    display_name: str,
    corpus: str,
    scope: str,
    dept_list: list[str],
    scope_registry_uri: str,
    tags: dict,
    init_fn,
) -> dict:
    """Fallback upload without metadata kwarg (older SDK)."""
    try:
        import re
        import tempfile
        from vertexai.preview import rag

        init_fn(corpus)
        ext = os.path.splitext(display_name)[1].lower() or ".txt"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write((extracted_text or "").encode("utf-8"))
            tmp_path = tmp.name
        try:
            rag_file = rag.upload_file(
                corpus_name=corpus,
                path=tmp_path,
                display_name=display_name[:1000],
            )
        finally:
            os.unlink(tmp_path)

        _register(rag_file.name, scope, dept_list, scope_registry_uri)
        return {
            "status": "success",
            "rag_file_name": rag_file.name,
            "display_name": rag_file.display_name,
            "accessibility_scope": scope,
            "departments": dept_list if scope == "department" else [],
            "tags_applied": {},
            "message": f"'{display_name}' uploaded (metadata tags not applied — SDK version limitation).",
        }
    except Exception as exc:
        logger.error("_upload_no_metadata fallback error: %s", exc)
        return {"status": "error", "message": str(exc)}


def get_tools() -> list[Callable]:
    from config import get_config
    return build_dm_tools(config_getter=get_config)
