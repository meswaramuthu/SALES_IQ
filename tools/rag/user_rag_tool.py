"""User-scoped RAG tools for Knowledge IQ.

All documents are stored in a single shared Vertex AI RAG corpus, but each
user can only search and manage their own uploaded files. Isolation is
enforced via RagResource.rag_file_ids at retrieval time, and via the GCS
user-file registry at upload/delete time.

User identity comes from tool_context.user_id, which Gemini Enterprise
(Agentspace) populates automatically with the authenticated Google Workspace
email. No login flow is needed.

Tools exposed:
    search_knowledge_base   — semantic search over the user's own files only
    upload_attachment       — ingest a file attached via the 📎 icon in chat
    upload_document         — ingest a Google Drive URL or GCS URI
    list_my_documents       — list the user's uploaded files
    delete_my_document      — delete one of the user's files
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import tempfile
from typing import Callable

logger = logging.getLogger(__name__)

_DRIVE_URL_RE = re.compile(r"https://drive\.google\.com/")
_SUPPORTED_MIME_EXTS: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/html": ".html",
    "application/json": ".json",
    "text/x-python": ".py",
    "text/x-sql": ".sql",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_user_id(tool_context) -> str:
    """Return user identity from the ADK tool context.

    Gemini Enterprise / Agentspace sets session.user_id to the authenticated
    Google Workspace email. Falls back to "anonymous" in local dev.
    """
    uid = getattr(tool_context, "user_id", None) or ""
    return uid.strip() or "anonymous"


def _require_user_id(tool_context) -> tuple[str, dict | None]:
    """Return (user_id, None) on success or ("", error_dict) if anonymous."""
    uid = _get_user_id(tool_context)
    if uid == "anonymous":
        return "", {
            "status": "error",
            "message": (
                "Cannot identify you. This tool requires a Gemini Enterprise "
                "session with an authenticated Google Workspace account."
            ),
        }
    return uid, None


def _init_for_corpus(corpus_name: str) -> None:
    """Re-initialise Vertex AI SDK to the corpus region."""
    import vertexai

    m = re.search(r"projects/([^/]+)/locations/([^/]+)/", corpus_name)
    if not m:
        return
    project, location = m.group(1), m.group(2)
    from google.cloud.aiplatform import initializer

    if getattr(initializer.global_config, "location", None) != location:
        vertexai.init(project=project, location=location)


def _is_access_control_enabled(cfg_config: dict) -> bool:
    """Return True if per-user RAG access control is active.

    Controlled by admin_access_control_enabled in tools_config.json (GCS-backed).
    When False, every user gets full corpus access (all files visible to all users).
    When True, only admin_users see all files; others see only their own uploads.
    """
    return bool(cfg_config.get("admin_access_control_enabled", False))


def _is_admin(user_id: str, cfg_config: dict) -> bool:
    """Return True if user_id is in the configured admin_users list.

    Non-email user_ids (e.g. the local ADK dev UI default "user") are treated
    as admin so local testing always gets full corpus access.
    """
    if "@" not in user_id:
        # Local ADK dev session — not a real authenticated workspace user.
        return True
    return user_id in cfg_config.get("admin_users", [])


def _ext_from_mime(mime_type: str) -> str:
    if mime_type in _SUPPORTED_MIME_EXTS:
        return _SUPPORTED_MIME_EXTS[mime_type]
    guessed = mimetypes.guess_extension(mime_type)
    return guessed or ".bin"


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def build_user_rag_tools(config_getter: Callable) -> list[Callable]:
    """Return all user-scoped RAG tool functions wired to config_getter."""

    # ------------------------------------------------------------------
    # SEARCH
    # ------------------------------------------------------------------

    def search_knowledge_base(query: str, tool_context=None) -> dict:
        """Search your personal knowledge base using semantic similarity.

        Only YOUR uploaded documents are searched — other users' files are
        never included. Returns an empty result if you have not uploaded
        any documents yet.

        Args:
            query: Natural language question or search terms.

        Returns:
            dict with a list of matching chunks (source, text, score).
        """
        cfg = config_getter().tools.get("rag")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Personal Knowledge Base is currently disabled."}

        if tool_context is None:
            return {"status": "error", "message": "No tool context available."}

        user_id, err = _require_user_id(tool_context)
        if err:
            return err

        registry_uri = cfg.config.get("user_file_registry_uri", "")
        corpus = cfg.config.get("corpus", "")
        if not corpus:
            return {"status": "error", "message": "RAG corpus is not configured."}

        try:
            from vertexai.preview import rag

            _init_for_corpus(corpus)

            access_ctrl = _is_access_control_enabled(cfg.config)
            is_admin = access_ctrl and _is_admin(user_id, cfg.config)

            if not access_ctrl or is_admin:
                # Access control disabled (open mode) OR admin user: search full corpus.
                logger.info("search_knowledge_base: full corpus search for user=%s (access_control=%s)", user_id, access_ctrl)
                rag_resource = rag.RagResource(rag_corpus=corpus)
            else:
                from stratova_shared.user_file_registry import get_user_files

                file_names = get_user_files(user_id, registry_uri)
                if not file_names:
                    # User has no personal uploads yet — return empty results without
                    # a blocking message so the LLM continues to search other tools.
                    logger.info("search_knowledge_base: no personal files for user=%s — returning empty", user_id)
                    return {"results": [], "count": 0}
                rag_resource = rag.RagResource(
                    rag_corpus=corpus,
                    rag_file_ids=[n.split("/")[-1] for n in file_names],
                )

            response = rag.retrieval_query(
                rag_resources=[rag_resource],
                text=query,
                similarity_top_k=cfg.config.get("similarity_top_k", 10),
                vector_distance_threshold=cfg.config.get("vector_distance_threshold", 0.6),
            )
            results = []
            for ctx in response.contexts.contexts:
                source_uri = ctx.source_uri or ""
                display_name = ctx.source_display_name or source_uri
                # source_uri is a real URL only for Drive/GCS imports; for
                # directly-uploaded files it equals the display name (not a URL).
                if source_uri.startswith("https://"):
                    web_link = source_uri
                else:
                    web_link = ""
                results.append(
                    {
                        "source": source_uri,
                        "display_name": display_name,
                        "web_link": web_link,
                        "text": ctx.text,
                        "score": round(ctx.score, 4),
                    }
                )
            return {"results": results, "count": len(results)}
        except Exception as exc:
            logger.error("search_knowledge_base error for user=%s: %s", user_id, exc)
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # UPLOAD — attachment from chat (📎 icon)
    # ------------------------------------------------------------------

    async def upload_attachment(
        display_name: str = "",
        extracted_text: str = "",
        tool_context=None,
    ) -> dict:
        """Save a file you attached in this chat to your personal knowledge base.

        Use this when the user has attached a file via the 📎 attachment icon
        in the Gemini Enterprise chat.

        IMPORTANT — Agentspace file delivery:
        When a file is uploaded in Gemini Enterprise, Agentspace injects text
        placeholder tags into the message:
            <start_of_user_uploaded_file: FILENAME>
            <end_of_user_uploaded_file: FILENAME>
        The actual file bytes are visible to you (the model) as a multimodal
        attachment, but are NOT passed to the tool as bytes.

        To upload the file you MUST:
          1. Extract the full text content from the file (you can read it).
          2. Call upload_attachment(extracted_text=<full_text>,
                                   display_name=<filename>)

        The extracted_text will be ingested into the knowledge base as plain
        text and will be fully searchable.

        Supported file types: PDF, DOCX, PPTX, TXT, MD, HTML, JSON, PY, SQL.

        Args:
            display_name: Friendly name / filename for the document.
                          Use the original filename if possible.
            extracted_text: The full text content you extracted from the file.
                            Required when the file was uploaded via the
                            Agentspace 📎 icon (as opposed to a Drive URL).

        Returns:
            dict with upload status and file details.
        """
        cfg = config_getter().tools.get("rag")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Personal Knowledge Base is currently disabled."}

        if tool_context is None:
            return {"status": "error", "message": "No tool context available."}

        user_id, err = _require_user_id(tool_context)
        if err:
            return err

        corpus = cfg.config.get("corpus", "")
        registry_uri = cfg.config.get("user_file_registry_uri", "")
        if not corpus:
            return {"status": "error", "message": "RAG corpus is not configured."}

        def _upload_bytes(file_bytes: bytes, mime_type: str, original_name: str) -> dict:
            """Upload raw bytes to RAG and register to user's file list."""
            ext = _ext_from_mime(mime_type)
            chosen_name = display_name or original_name
            try:
                from vertexai.preview import rag

                _init_for_corpus(corpus)
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(file_bytes)
                    tmp_path = tmp.name
                try:
                    rag_file = rag.upload_file(
                        corpus_name=corpus,
                        path=tmp_path,
                        display_name=chosen_name,
                    )
                finally:
                    os.unlink(tmp_path)

                from stratova_shared.user_file_registry import add_user_files

                add_user_files(user_id, [rag_file.name], registry_uri)
                logger.info("upload_attachment: user=%s file=%s", user_id, rag_file.name)
                return {
                    "status": "success",
                    "file_name": rag_file.name,
                    "display_name": rag_file.display_name,
                    "message": f"'{chosen_name}' has been added to your personal knowledge base.",
                }
            except Exception as exc:
                logger.error("upload_attachment error for user=%s: %s", user_id, exc)
                return {"status": "error", "message": str(exc)}

        # --- Path 0: LLM-extracted text (Agentspace file placeholder flow) ---
        # Agentspace does NOT send file bytes to Agent Engine. It injects text
        # placeholders: <start_of_user_uploaded_file: FILENAME> … <end_of_user_uploaded_file: FILENAME>
        # The Gemini model can read the file multimodally and must extract the
        # text then call upload_attachment(extracted_text=..., display_name=...).
        if extracted_text and extracted_text.strip():
            chosen_name = display_name or "uploaded_document.txt"
            if not any(chosen_name.lower().endswith(ext) for ext in (
                ".txt", ".md", ".pdf", ".docx", ".pptx", ".html", ".json", ".py", ".sql"
            )):
                chosen_name += ".txt"
            logger.info(
                "upload_attachment: Path 0 (extracted_text) user=%s name=%s chars=%d",
                user_id, chosen_name, len(extracted_text),
            )
            return _upload_bytes(extracted_text.encode("utf-8"), "text/plain", chosen_name)

        # --- Path 1 & 2: scan user_content.parts for inline bytes or URI refs ---
        # tool_context is ADK Context which wraps _invocation_context.
        # user_content lives on InvocationContext, not on the public Context API.
        inv_ctx = getattr(tool_context, "_invocation_context", None)
        user_content = getattr(inv_ctx, "user_content", None)
        parts = getattr(user_content, "parts", None) or []
        logger.info("upload_attachment: user=%s parts_count=%d", user_id, len(parts))

        # Detect Agentspace text placeholder so we can name the file correctly
        _agentspace_filename = ""
        for _p in parts:
            _txt = getattr(_p, "text", "") or ""
            _m = re.search(r"<start_of_user_uploaded_file:\s*(.+?)>", _txt)
            if _m:
                _agentspace_filename = _m.group(1).strip()
                break

        for idx, part in enumerate(parts):
            inline = getattr(part, "inline_data", None)
            file_data_obj = getattr(part, "file_data", None)
            logger.info(
                "upload_attachment: user=%s part[%d] "
                "text=%r has_inline=%s inline_mime=%r inline_data_len=%s "
                "has_file_data=%s file_uri=%r",
                user_id, idx,
                (getattr(part, "text", None) or "")[:80],
                inline is not None,
                getattr(inline, "mime_type", None) if inline else None,
                len(getattr(inline, "data", None) or b"") if inline else "N/A",
                file_data_obj is not None,
                getattr(file_data_obj, "file_uri", "") if file_data_obj else "",
            )

            # Path 1: inline raw bytes embedded in the message
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return _upload_bytes(
                    inline.data,
                    inline.mime_type or "application/octet-stream",
                    getattr(inline, "display_name", None) or "document",
                )

            file_data = getattr(part, "file_data", None)
            if file_data:
                file_uri = getattr(file_data, "file_uri", "") or ""

                # Path 2a: GCS URI — delegate to upload_document
                if file_uri.startswith("gs://"):
                    return upload_document(
                        source=file_uri,
                        display_name=display_name,
                        tool_context=tool_context,
                    )

                # Path 2b: ADK artifact:// URI — load via artifact service
                # Agentspace converts inline uploads to artifact:// refs when
                # save_input_blobs_as_artifacts is enabled on the runner.
                # URI format: artifact://apps/{app}/users/{uid}/sessions/{sid}/artifacts/{name}/versions/{n}
                if file_uri.startswith("artifact://"):
                    m = re.search(r"/artifacts/([^/]+)/versions/", file_uri)
                    if m:
                        artifact_name = m.group(1)
                        try:
                            artifact = await tool_context.load_artifact(artifact_name)
                            # Try user-scoped artifact if session-scoped not found
                            if artifact is None and not artifact_name.startswith("user:"):
                                artifact = await tool_context.load_artifact(f"user:{artifact_name}")
                            a_inline = artifact and getattr(artifact, "inline_data", None)
                            if a_inline and getattr(a_inline, "data", None):
                                return _upload_bytes(
                                    a_inline.data,
                                    a_inline.mime_type or "application/octet-stream",
                                    display_name or artifact_name,
                                )
                        except Exception as exc:
                            logger.warning("Artifact %s load failed: %s", artifact_name, exc)
                else:
                    # Unknown URI scheme — log so we can diagnose in Cloud Logging
                    logger.warning(
                        "upload_attachment: unhandled file_data URI scheme for user=%s uri=%r "
                        "(not gs:// or artifact://) — falling through to artifact service fallback",
                        user_id, file_uri,
                    )

        # --- Path 3: artifact service fallback ---
        # When no file appears in user_content.parts, check the artifact service
        # directly. This covers Gemini Enterprise flows where uploaded files are
        # stored as session artifacts without a corresponding file_data part.
        try:
            artifact_names = await tool_context.list_artifacts()
            logger.info(
                "upload_attachment: artifact service returned %d artifact(s) for user=%s: %s",
                len(artifact_names or []), user_id, artifact_names,
            )
            for artifact_name in (artifact_names or []):
                try:
                    artifact = await tool_context.load_artifact(artifact_name)
                    a_inline = artifact and getattr(artifact, "inline_data", None)
                    if a_inline and getattr(a_inline, "data", None):
                        result = _upload_bytes(
                            a_inline.data,
                            a_inline.mime_type or "application/octet-stream",
                            display_name or artifact_name,
                        )
                        if result.get("status") == "success":
                            return result
                except Exception as exc:
                    logger.warning("Artifact %s processing failed: %s", artifact_name, exc)
        except Exception as exc:
            logger.warning("upload_attachment: artifact service unavailable for user=%s: %s", user_id, exc)

        # --- Agentspace placeholder detected but no extracted_text supplied ---
        # The LLM can see the file multimodally; prompt it to extract and re-call.
        if _agentspace_filename:
            logger.info(
                "upload_attachment: Agentspace placeholder detected name=%r — "
                "prompting LLM to extract text",
                _agentspace_filename,
            )
            return {
                "status": "action_required",
                "filename": _agentspace_filename,
                "message": (
                    f"The file '{_agentspace_filename}' is in your multimodal context — "
                    "you CAN read it right now.\n\n"
                    "ACTION REQUIRED: Read EVERY page / slide of the file and copy ALL "
                    "visible text verbatim (every heading, paragraph, bullet point, table "
                    "cell, caption — every single word on every page). "
                    "Do NOT write placeholder sentences like 'This is the content of...' "
                    "or 'The document is about...'. Those are fabrications — copy the "
                    "ACTUAL words you see in the file.\n\n"
                    f"Then call: upload_attachment("
                    f"display_name='{_agentspace_filename}', "
                    "extracted_text=<ALL verbatim text from every page of the file>)"
                ),
            }

        return {
            "status": "error",
            "message": (
                "No file attachment found in your message. "
                "Please attach a file using the 📎 icon in the chat, "
                "or share a Google Drive URL using the upload_document tool."
            ),
        }

    # ------------------------------------------------------------------
    # UPLOAD — Drive URL or GCS URI
    # ------------------------------------------------------------------

    def upload_document(source: str, display_name: str = "", tool_context=None) -> dict:
        """Add a document to your personal knowledge base via a URL or GCS path.

        Supported source formats:
          - Google Drive file:    https://drive.google.com/file/d/FILE_ID/view
          - Google Drive folder:  https://drive.google.com/drive/folders/FOLDER_ID
          - GCS URI:              gs://bucket-name/path/to/document.pdf

        For Google Drive files, you must first share the file or folder with
        the Vertex AI service account (the error message will show the email
        if access is denied).

        Supported file types: PDF, DOCX, PPTX, TXT, MD, RST, HTML, JSON, PY, SQL.

        Args:
            source: A Google Drive URL or GCS URI.
            display_name: Optional friendly name for the document.

        Returns:
            dict with upload status and count of imported documents.
        """
        cfg = config_getter().tools.get("rag")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Personal Knowledge Base is currently disabled."}

        if tool_context is None:
            return {"status": "error", "message": "No tool context available."}

        user_id, err = _require_user_id(tool_context)
        if err:
            return err

        # Validate source format.
        source = (source or "").strip()
        is_gcs = source.startswith("gs://")
        is_drive = bool(_DRIVE_URL_RE.match(source))
        if not (is_gcs or is_drive):
            return {
                "status": "error",
                "message": (
                    "Invalid source format. Accepted formats:\n"
                    "  - Google Drive file:   https://drive.google.com/file/d/FILE_ID/view\n"
                    "  - Google Drive folder: https://drive.google.com/drive/folders/FOLDER_ID\n"
                    "  - GCS URI:             gs://bucket-name/path/to/document.pdf"
                ),
            }

        corpus = cfg.config.get("corpus", "")
        registry_uri = cfg.config.get("user_file_registry_uri", "")
        if not corpus:
            return {"status": "error", "message": "RAG corpus is not configured."}

        try:
            from vertexai.preview import rag

            _init_for_corpus(corpus)

            # Snapshot existing files before import so we can identify new ones.
            before: set[str] = {f.name for f in rag.list_files(corpus_name=corpus)}

            response = rag.import_files(
                corpus_name=corpus,
                paths=[source],
                chunk_size=cfg.config.get("chunk_size", 512),
                chunk_overlap=cfg.config.get("chunk_overlap", 100),
            )

            after: set[str] = {f.name for f in rag.list_files(corpus_name=corpus)}
            new_files = list(after - before)

            if new_files:
                from stratova_shared.user_file_registry import add_user_files

                add_user_files(user_id, new_files, registry_uri)

            imported = getattr(response, "imported_rag_files_count", len(new_files))
            failed = getattr(response, "failed_rag_files_count", 0)
            logger.info(
                "upload_document: user=%s imported=%d failed=%d source=%s",
                user_id, imported, failed, source,
            )
            return {
                "status": "success",
                "source": source,
                "imported": imported,
                "failed": failed,
                "message": (
                    f"Successfully added {imported} document(s) to your personal knowledge base."
                    if imported
                    else "No documents were imported. Check that the file format is supported and the source is accessible."
                ),
            }
        except Exception as exc:
            logger.error("upload_document error for user=%s: %s", user_id, exc)
            err_msg = str(exc)
            # Surface Drive access hint when it looks like a permission error.
            if "PERMISSION_DENIED" in err_msg or "403" in err_msg:
                err_msg += (
                    "\n\nIf this is a Google Drive file, please share it with the "
                    "Vertex AI service account. You can find the service account email "
                    "in the Google Cloud Console under IAM & Admin → Service Accounts."
                )
            return {"status": "error", "message": err_msg}

    # ------------------------------------------------------------------
    # LIST
    # ------------------------------------------------------------------

    def list_my_documents(tool_context=None) -> dict:
        """List all documents you have uploaded to your personal knowledge base.

        Returns:
            dict with a list of your documents including name and display_name.
        """
        cfg = config_getter().tools.get("rag")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Personal Knowledge Base is currently disabled."}

        if tool_context is None:
            return {"status": "error", "message": "No tool context available."}

        user_id, err = _require_user_id(tool_context)
        if err:
            return err

        registry_uri = cfg.config.get("user_file_registry_uri", "")
        corpus = cfg.config.get("corpus", "")

        access_ctrl = _is_access_control_enabled(cfg.config)
        is_admin = access_ctrl and _is_admin(user_id, cfg.config)

        try:
            from vertexai.preview import rag

            _init_for_corpus(corpus)

            if not access_ctrl or is_admin:
                # Access control disabled (open mode) OR admin: list all corpus files.
                all_corpus_files = list(rag.list_files(corpus_name=corpus))
                items = [
                    {
                        "name": f.name,
                        "display_name": f.display_name,
                        "size_bytes": getattr(f, "size_bytes", None),
                        "create_time": str(getattr(f, "create_time", "")),
                    }
                    for f in all_corpus_files
                ]
                scope = "all (admin)" if is_admin else "all"
                return {"files": items, "count": len(items), "scope": scope}

            # Per-user mode: list only the user's own registered files.
            from stratova_shared.user_file_registry import get_user_files

            file_names = get_user_files(user_id, registry_uri)
            if not file_names:
                return {
                    "files": [],
                    "count": 0,
                    "message": (
                        "Your personal knowledge base is empty. "
                        "Upload a document using the 📎 attachment icon or by sharing a Google Drive URL."
                    ),
                }

            name_set = set(file_names)
            items = [
                {
                    "name": f.name,
                    "display_name": f.display_name,
                    "size_bytes": getattr(f, "size_bytes", None),
                    "create_time": str(getattr(f, "create_time", "")),
                }
                for f in rag.list_files(corpus_name=corpus)
                if f.name in name_set
            ]
            return {"files": items, "count": len(items)}

        except Exception as exc:
            logger.error("list_my_documents error for user=%s: %s", user_id, exc)
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    def delete_my_document(file_name: str, tool_context=None) -> dict:
        """Delete a document from your personal knowledge base.

        You can only delete documents that belong to you. Use list_my_documents
        to get the full resource name of the file you want to remove.

        Args:
            file_name: The full resource name of the document
                       (e.g. projects/.../ragCorpora/.../ragFiles/...).

        Returns:
            dict with deletion status.
        """
        cfg = config_getter().tools.get("rag")
        if not cfg or not cfg.enabled:
            return {"status": "disabled", "message": "Personal Knowledge Base is currently disabled."}

        if tool_context is None:
            return {"status": "error", "message": "No tool context available."}

        user_id, err = _require_user_id(tool_context)
        if err:
            return err

        registry_uri = cfg.config.get("user_file_registry_uri", "")

        from stratova_shared.user_file_registry import is_user_file, remove_user_file

        # Admin override only applies when access control is enabled.
        is_admin = _is_access_control_enabled(cfg.config) and _is_admin(user_id, cfg.config)

        # Authorization: admin can delete any file; all others only their own.
        if not is_admin and not is_user_file(user_id, file_name, registry_uri):
            return {
                "status": "error",
                "message": "You can only delete documents from your own personal knowledge base.",
            }

        try:
            from vertexai.preview import rag

            _init_for_corpus(file_name)
            rag.delete_file(name=file_name)
            # Always clean up the registry entry regardless of who owned the file.
            remove_user_file(user_id, file_name, registry_uri)
            # If admin deleted someone else's file, remove it from the owner's registry too.
            if is_admin:
                from stratova_shared.user_file_registry import remove_file_from_all_users
                try:
                    remove_file_from_all_users(file_name, registry_uri)
                except Exception as reg_exc:
                    logger.warning("delete_my_document: registry cleanup error: %s", reg_exc)

            logger.info("delete_my_document: user=%s deleted=%s (admin=%s)", user_id, file_name, is_admin)
            return {
                "status": "success",
                "deleted": file_name,
                "message": "The document has been removed from the knowledge base.",
            }
        except Exception as exc:
            logger.error("delete_my_document error for user=%s: %s", user_id, exc)
            return {"status": "error", "message": str(exc)}

    return [
        search_knowledge_base,
        upload_attachment,
        upload_document,
        list_my_documents,
        delete_my_document,
    ]


def get_tools() -> list[Callable]:
    from config import get_config

    return build_user_rag_tools(config_getter=get_config)
