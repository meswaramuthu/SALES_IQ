#!/usr/bin/env python3
"""Upload a prompt text file to GCS to change the agent's system prompt at runtime.

The {tool_status} placeholder in the prompt is automatically filled in with the
current enable/disable state of each tool — include it in your custom prompt.

Usage:
    uv run python scripts/upload_prompt.py config/prompt.txt
    uv run python scripts/upload_prompt.py my_prompt.txt --gcs-uri gs://bucket/path/prompt.txt
"""
import argparse
import os
import re
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload prompt.txt to GCS")
    parser.add_argument("prompt_file", help="Path to the prompt text file")
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

    m = re.match(r"gs://([^/]+)/(.+)", args.gcs_uri)
    if not m:
        sys.exit(f"Invalid GCS URI: {args.gcs_uri}")

    from google.cloud import storage

    bucket_name, blob_name = m.group(1), m.group(2)
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_filename(str(path), content_type="text/plain")

    print(f"Uploaded {path} to {args.gcs_uri}")
    print("New prompt takes effect on the next agent invocation (no redeploy needed).")


if __name__ == "__main__":
    main()
