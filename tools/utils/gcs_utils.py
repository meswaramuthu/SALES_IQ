"""GCS read/write utilities.

Inlined here so the sync Docker image (which does not bundle stratova_shared)
can load tools_config.json from GCS without an import error.
When stratova_shared IS present (agent deployment), both modules expose the
same API so existing imports continue to work.
"""
from __future__ import annotations

import re


def _parse(gcs_uri: str) -> tuple[str, str]:
    m = re.match(r"gs://([^/]+)/(.+)", gcs_uri)
    if not m:
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
    return m.group(1), m.group(2)


def read_gcs_text(gcs_uri: str) -> str:
    from google.cloud import storage
    bucket, blob = _parse(gcs_uri)
    return storage.Client().bucket(bucket).blob(blob).download_as_text()


def read_gcs_bytes(gcs_uri: str) -> bytes:
    from google.cloud import storage
    bucket, blob = _parse(gcs_uri)
    return storage.Client().bucket(bucket).blob(blob).download_as_bytes()


def write_gcs_text(gcs_uri: str, content: str, content_type: str = "text/plain") -> None:
    from google.cloud import storage
    bucket, blob = _parse(gcs_uri)
    storage.Client().bucket(bucket).blob(blob).upload_from_string(content, content_type=content_type)
