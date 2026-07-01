#!/usr/bin/env python3
"""Upload AURA_orch/prompt.md to GCS to update the AURA system prompt at runtime.

Usage:
    uv run python deploy/scripts/upload_prompt.py AURA_orch/prompt.md
    uv run python deploy/scripts/upload_prompt.py AURA_orch/prompt.md --gcs-uri gs://bucket/path/prompt.md
"""
import argparse
import os
import re
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload AURA prompt to GCS")
    parser.add_argument("prompt_file", help="Path to prompt.md")
    parser.add_argument(
        "--gcs-uri",
        default=os.environ.get("PROMPT_GCS_URI"),
        help="Destination GCS URI (defaults to PROMPT_GCS_URI env var)",
    )
    args = parser.parse_args()

    if not args.gcs_uri:
        sys.exit("Error: provide --gcs-uri or set PROMPT_GCS_URI")

    path = Path(args.prompt_file)
    if not path.exists():
        sys.exit(f"Error: {path} not found")

    prompt_text = path.read_text(encoding="utf-8")
    if not prompt_text.strip():
        sys.exit("Error: prompt file is empty")

    m = re.match(r"gs://([^/]+)/(.+)", args.gcs_uri)
    if not m:
        sys.exit(f"Invalid GCS URI: {args.gcs_uri}")

    from google.cloud import storage

    bucket_name, blob_name = m.group(1), m.group(2)
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_string(prompt_text, content_type="text/plain")

    char_count = len(prompt_text)
    line_count = prompt_text.count("\n")
    print(f"Uploaded to {args.gcs_uri}")
    print(f"Prompt: {char_count} characters, {line_count} lines")
    print("Changes take effect within CONFIG_CACHE_TTL_SECONDS (default 60s).")


if __name__ == "__main__":
    main()
