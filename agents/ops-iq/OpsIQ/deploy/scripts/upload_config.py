"""Upload tools_config.json to GCS.

Usage:
    cd new_folder_structure/agents/ops-iq/OpsIQ
    PYTHONPATH="$(pwd):$(pwd)/../../../.." python deploy/scripts/upload_config.py
"""
import json
import os
import sys
from pathlib import Path

# Add new_folder_structure/ to path so tools.utils.gcs_utils resolves
_nfs_root = Path(__file__).parents[5].resolve()
sys.path.insert(0, str(_nfs_root))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")


def main() -> None:
    config_path = Path(__file__).parents[2] / "config" / "tools_config.json"
    gcs_uri = os.environ.get(
        "TOOLS_CONFIG_GCS_URI",
        "gs://stratova-platform/agents/ops-iq/config/tools_config.json",
    )

    if not config_path.exists():
        print(f"ERROR: config file not found: {config_path}")
        sys.exit(1)

    data = json.loads(config_path.read_text())
    print(f"Uploading {config_path} → {gcs_uri}")

    from tools.utils.gcs_utils import write_gcs_text

    write_gcs_text(gcs_uri, json.dumps(data, indent=2))
    print(f"Config uploaded to {gcs_uri}")
    print("Changes take effect within CONFIG_CACHE_TTL_SECONDS (default: 60s).")


if __name__ == "__main__":
    main()
