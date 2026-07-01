#!/usr/bin/env python3
"""Upload tools_config.json to GCS to update tool enable/disable state at runtime.

Usage:
    uv run python deploy/scripts/upload_config.py AURA_orch/tools_config.json
    uv run python deploy/scripts/upload_config.py AURA_orch/tools_config.json --gcs-uri gs://bucket/path/config.json
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload tools_config.json to GCS")
    parser.add_argument("config_file", help="Path to tools_config.json")
    parser.add_argument(
        "--gcs-uri",
        default=os.environ.get("TOOLS_CONFIG_GCS_URI"),
        help="Destination GCS URI (defaults to TOOLS_CONFIG_GCS_URI env var)",
    )
    args = parser.parse_args()

    if not args.gcs_uri:
        sys.exit("Error: provide --gcs-uri or set TOOLS_CONFIG_GCS_URI")

    path = Path(args.config_file)
    if not path.exists():
        sys.exit(f"Error: {path} not found")

    # Validate JSON before uploading
    with open(path) as f:
        config = json.load(f)

    m = re.match(r"gs://([^/]+)/(.+)", args.gcs_uri)
    if not m:
        sys.exit(f"Invalid GCS URI: {args.gcs_uri}")

    from google.cloud import storage

    bucket_name, blob_name = m.group(1), m.group(2)
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_string(json.dumps(config, indent=2), content_type="application/json")

    enabled_tools = [k for k, v in config.get("tools", {}).items() if v.get("enabled")]
    enabled_agents = [k for k, v in config.get("sub_agents", {}).items() if v.get("enabled")]
    print(f"Uploaded to {args.gcs_uri}")
    print(f"Enabled tools: {', '.join(enabled_tools) or '(none)'}")
    print(f"Enabled sub-agents: {', '.join(enabled_agents) or '(none)'}")
    print("Changes take effect within CONFIG_CACHE_TTL_SECONDS (default 60s).")


if __name__ == "__main__":
    main()
