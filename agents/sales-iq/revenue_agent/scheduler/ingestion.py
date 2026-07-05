"""Vertex AI RAG ingestion helpers — upload and delete individual documents.

Uses rag.upload_file() rather than rag.import_files() so we get back a concrete
RAG file resource name. Storing that name in sync state is what enables targeted
deletion when a source document is removed or replaced.

Supported file extensions mirror the Vertex AI RAG ingestion pipeline. Binary
formats (PDF, DOCX) are passed through as-is — Vertex handles chunking. Plain-text
formats are written directly. Files outside RAG_SUPPORTED_EXTS are silently skipped.

Metadata enrichment:
  Each uploaded file gets user_metadata with source context (source, file_ext,
  last_modified, repo/site) plus AI-extracted fields (doc_type, topic, keywords)
  from keyword_extractor.py. This enables metadata-filtered retrieval at query time.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB — skip anything larger

# Extensions actually accepted by the Vertex AI RAG ingestion pipeline.
# Confirmed unsupported (API returns code 3 "extension not supported"):
#   .ts .tsx .jsx .js .yml .yaml .sh .r .scala .kt .swift .rs .java .cs
#   .cpp .c .h .go .rb .php .toml .ini .cfg
# Note: .csv was historically unsupported but Vertex AI added support;
#   uploads that still fail will be caught and logged as errors.
# Not added (binary/media — RAG pipeline rejects these):
#   .png .obj .mp4 .rar .zip .webm .eps .url .mtl
RAG_SUPPORTED_EXTS = frozenset({
    # Documents
    ".pdf", ".docx", ".pptx", ".txt", ".md", ".rst",
    # Web
    ".html", ".htm",
    # Data / code actually accepted
    ".json", ".py", ".sql",
    # Spreadsheets & tabular data
    ".xlsx", ".csv",
    # Images (Vertex AI RAG supports JPEG for multimodal corpora)
    ".jpeg", ".jpg",
})


def _init_vertexai(corpus_name: str) -> None:
    """Re-init Vertex AI to the region encoded in the corpus resource name."""
    import vertexai
    from google.cloud.aiplatform import initializer

    m = re.search(r"projects/([^/]+)/locations/([^/]+)/", corpus_name)
    if not m:
        return
    project, location = m.group(1), m.group(2)
    if getattr(initializer.global_config, "location", None) != location:
        vertexai.init(project=project, location=location)


def upload_to_rag(
    content: bytes,
    filename: str,
    display_name: str,
    corpus_name: str,
    description: str = "",
    source_metadata: Optional[dict] = None,
) -> Optional[str]:
    """Upload raw bytes to Vertex AI RAG. Returns the rag_file resource name, or None on failure.

    source_metadata keys accepted (all optional):
        source       — "sharepoint" | "github"
        repo         — "owner/repo" (GitHub)
        site         — SharePoint site name
        file_ext     — ".pdf", ".md", etc.
        last_modified — ISO date string

    AI-extracted keywords (doc_type, topic, keywords) are appended automatically.
    """
    if len(content) == 0:
        logger.debug("Skipping %s — empty file", filename)
        return None

    if len(content) > _MAX_FILE_BYTES:
        logger.warning("Skipping %s — file too large (%d bytes)", filename, len(content))
        return None

    ext = os.path.splitext(filename)[1].lower() or ".txt"
    if ext not in RAG_SUPPORTED_EXTS:
        logger.debug("Skipping %s — unsupported extension %s", filename, ext)
        return None

    # Build user_metadata: source context + AI-extracted keywords
    user_metadata: dict[str, str] = {}
    if source_metadata:
        user_metadata.update({k: str(v) for k, v in source_metadata.items() if v})

    try:
        from scheduler.keyword_extractor import extract_metadata
        extracted = extract_metadata(content, filename)
        user_metadata.update(extracted)
    except Exception as exc:
        logger.debug("Keyword extraction failed for %s: %s", filename, exc)

    try:
        from vertexai.preview import rag

        _init_vertexai(corpus_name)

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            rag_file = rag.upload_file(
                corpus_name=corpus_name,
                path=tmp_path,
                display_name=display_name[:1000],
                description=description[:500],
                **({"metadata": user_metadata} if user_metadata else {}),
            )
        finally:
            os.unlink(tmp_path)

        logger.info("Uploaded to RAG: %s → %s", display_name, rag_file.name)
        return rag_file.name

    except TypeError:
        # SDK version doesn't support metadata kwarg yet — retry without it
        try:
            from vertexai.preview import rag

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                rag_file = rag.upload_file(
                    corpus_name=corpus_name,
                    path=tmp_path,
                    display_name=display_name[:1000],
                    description=description[:500],
                )
            finally:
                os.unlink(tmp_path)
            logger.info("Uploaded to RAG (no metadata): %s → %s", display_name, rag_file.name)
            return rag_file.name
        except Exception as exc:
            logger.error("RAG upload failed for %s: %s", display_name, exc)
            return None

    except Exception as exc:
        logger.error("RAG upload failed for %s: %s", display_name, exc)
        return None


def delete_from_rag(rag_file_name: str) -> bool:
    """Delete a RAG file by its resource name. Returns True on success."""
    try:
        from vertexai.preview import rag

        _init_vertexai(rag_file_name)
        rag.delete_file(name=rag_file_name)
        logger.info("Deleted from RAG: %s", rag_file_name)
        return True
    except Exception as exc:
        logger.error("RAG deletion failed for %s: %s", rag_file_name, exc)
        return False
