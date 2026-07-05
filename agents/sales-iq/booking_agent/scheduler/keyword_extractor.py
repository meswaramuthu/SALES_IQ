"""Lightweight keyword/topic extractor for RAG metadata enrichment.

Uses Gemini Flash to extract doc_type, topic, and keywords from the first
~2 KB of file content. Result is stored in user_metadata on each RAG file,
enabling metadata-filtered retrieval at query time.

Extraction is best-effort: on any error it returns an empty dict so the
caller can still upload the file without metadata enrichment.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_SAMPLE_CHARS = 2000  # chars sent to Gemini — enough context, keeps cost tiny
_EXTRACTION_MODEL = "gemini-2.5-flash"

# Skip extraction for files where content metadata adds little value
_NO_EXTRACT_EXTS = frozenset({".json", ".toml", ".ini", ".cfg", ".csv", ".sql"})

_PROMPT = """\
Extract structured metadata from this document snippet. Return ONLY valid JSON, no markdown.

{{
  "doc_type": "<one of: sow, proposal, spec, readme, code, report, policy, meeting_notes, template, other>",
  "topic": "<2-4 word topic summary>",
  "keywords": "<up to 6 comma-separated lowercase keywords most relevant to the content>"
}}

Filename: {filename}
Content sample:
{sample}"""


def extract_metadata(content: bytes, filename: str) -> dict[str, str]:
    """Return doc_type/topic/keywords dict, or {} on any failure."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in _NO_EXTRACT_EXTS:
        return {}

    sample = content[:_SAMPLE_CHARS].decode("utf-8", errors="ignore").strip()
    if len(sample) < 50:
        return {}

    try:
        from vertexai.generative_models import GenerationConfig, GenerativeModel

        model = GenerativeModel(_EXTRACTION_MODEL)
        response = model.generate_content(
            _PROMPT.format(filename=filename, sample=sample),
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=120,
                temperature=0.0,
            ),
        )
        parsed = json.loads(response.text)
        return {
            k: str(v).strip()[:100]          # guard against oversized values
            for k, v in parsed.items()
            if k in ("doc_type", "topic", "keywords") and v
        }
    except Exception as exc:
        logger.debug("Keyword extraction skipped for %s: %s", filename, exc)
        return {}
