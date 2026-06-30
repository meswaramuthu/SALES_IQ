"""AI-powered document analysis for smart metadata extraction.

Uses Gemini Flash to analyze document content and extract:
  - doc_category  : high-level category (contract, financial, technical, hr_policy, …)
  - doc_type      : fine-grained type (sow, invoice, spec, meeting_notes, …)
  - topic         : 2-4 word summary
  - keywords      : up to 8 comma-separated keywords
  - suggested_departments : departments most likely to need this document
  - suggested_scope : "organization" or "department"

Best-effort — returns {} on any failure so upload proceeds without enrichment.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_SAMPLE_CHARS = 3000
_MODEL = "gemini-2.5-flash"
_NO_ANALYZE_EXTS = frozenset({".json", ".csv", ".sql"})

KNOWN_DEPARTMENTS = [
    "sales", "engineering", "hr", "finance", "legal",
    "marketing", "operations", "executive", "product", "support",
]

_PROMPT = """\
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
    """Return metadata dict, or {} on any failure.

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

        model = GenerativeModel(_MODEL)
        response = model.generate_content(
            _PROMPT.format(filename=filename, sample=sample),
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
