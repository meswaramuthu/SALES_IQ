"""Upload prompt.txt to GCS.

Usage:
    cd new_folder_structure/agents/ops-iq/OpsIQ
    PYTHONPATH="$(pwd):$(pwd)/../../../.." python deploy/scripts/upload_prompt.py
"""
import os
import sys
from pathlib import Path

# Add new_folder_structure/ to path so tools.utils.gcs_utils resolves
_nfs_root = Path(__file__).parents[5].resolve()
sys.path.insert(0, str(_nfs_root))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")


def main() -> None:
    prompt_path = Path(__file__).parents[2] / "config" / "prompt.txt"
    gcs_uri = os.environ.get(
        "PROMPT_GCS_URI",
        "gs://stratova-platform/agents/ops-iq/prompts/prompt.txt",
    )

    if not prompt_path.exists():
        print(f"ERROR: prompt file not found: {prompt_path}")
        sys.exit(1)

    content = prompt_path.read_text(encoding="utf-8")
    print(f"Uploading {prompt_path} → {gcs_uri}")

    from tools.utils.gcs_utils import write_gcs_text

    write_gcs_text(gcs_uri, content)
    print(f"Prompt uploaded to {gcs_uri}")
    print("Changes take effect on the next agent invocation (no redeploy needed).")


if __name__ == "__main__":
    main()
