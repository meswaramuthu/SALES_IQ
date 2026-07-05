#!/usr/bin/env python3
"""
Ops IQ — Central deploy / teardown script.

DEPLOY MODE (default)
  Phase 1 — GCP Infrastructure: Enable required APIs, validate staging bucket
  Phase 2 — Dynamic Config Upload: Upload tools_config.json + prompt.txt to GCS
  Phase 3 — Agent Engine Deployment: Package and deploy AdkApp to Vertex AI

DELETE MODE (--delete)
  Reads resource ID from deploy/deployment_state.json (auto-populated on deploy).
  Deletes the Agent Engine resource.

EXAMPLES
  # Full deploy (from new_folder_structure/agents/ops-iq/OpsIQ/)
  uv run python deploy/deploy_full.py --project ninth-archway-496404-s2

  # Skip infrastructure check (already set up)
  uv run python deploy/deploy_full.py --project ninth-archway-496404-s2 --skip-infrastructure

  # Teardown
  uv run python deploy/deploy_full.py --delete --project ninth-archway-496404-s2
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

_SCRIPT_DIR   = Path(__file__).parent.resolve()           # deploy/
_AGENT_ROOT   = _SCRIPT_DIR.parent.resolve()              # OpsIQ/
_REPO_ROOT    = _AGENT_ROOT.parents[2].resolve()          # laabu-ai-app/
_TOOLS_SRC    = _REPO_ROOT / "tools"                      # laabu-ai-app/tools/
_ENV_FILE     = _AGENT_ROOT / ".env"
_STATE_FILE   = _SCRIPT_DIR / "deployment_state.json"
_CONFIG_FILE  = _AGENT_ROOT / "config" / "tools_config.json"
_PROMPT_FILE  = _AGENT_ROOT / "config" / "prompt.txt"

# Add OpsIQ/ and new_folder_structure/ to path for imports
sys.path.insert(0, str(_AGENT_ROOT))
sys.path.insert(0, str(_NEW_FS_ROOT))

_REQUIREMENTS = [
    "google-cloud-aiplatform[adk,agent_engines]>=1.148.1,<2",
    "google-adk==1.34.3",
    "mcp==1.27.2",
    "python-dotenv",
    "google-cloud-monitoring>=2.22.0",
    "google-cloud-quotas>=0.1.5",
    "google-cloud-firestore>=2.19.0",
    "google-cloud-storage>=2.0",
    "google-auth>=2.36.0",
    "pydantic>=2.0",
    "requests>=2.32.3",
]

_REQUIRED_APIS = [
    "aiplatform.googleapis.com",
    "monitoring.googleapis.com",
    "cloudquotas.googleapis.com",
    "firestore.googleapis.com",
    "storage.googleapis.com",
]


def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    _STATE_FILE.write_text(json.dumps(state, indent=2))


def _run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    log.info("$ %s", " ".join(cmd))
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def phase1_infrastructure(project: str, staging_bucket: str) -> None:
    log.info("── Phase 1: GCP Infrastructure ──")
    log.info("Enabling required APIs (idempotent)…")
    _run(["gcloud", "services", "enable"] + _REQUIRED_APIS + ["--project", project, "--quiet"])

    if staging_bucket:
        bucket = staging_bucket.lstrip("gs://").split("/")[0]
        result = _run(
            ["gcloud", "storage", "buckets", "describe", f"gs://{bucket}", "--project", project],
            check=False, capture=True,
        )
        if result.returncode != 0:
            log.info("Creating staging bucket gs://%s …", bucket)
            _run(["gcloud", "storage", "buckets", "create", f"gs://{bucket}",
                  "--project", project, "--location", "us-central1"])
        else:
            log.info("Staging bucket gs://%s already exists.", bucket)
    log.info("Phase 1 complete.")


def phase2_upload_config(project: str) -> dict[str, str]:
    log.info("── Phase 2: Dynamic Config Upload ──")
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE)
    from tools.utils.gcs_utils import write_gcs_text

    config_gcs_uri = os.environ.get(
        "TOOLS_CONFIG_GCS_URI",
        f"gs://stratova-platform/agents/ops-iq/config/tools_config.json",
    )
    prompt_gcs_uri = os.environ.get(
        "PROMPT_GCS_URI",
        f"gs://stratova-platform/agents/ops-iq/prompts/prompt.txt",
    )

    if _CONFIG_FILE.exists():
        log.info("Uploading tools_config.json → %s", config_gcs_uri)
        write_gcs_text(config_gcs_uri, _CONFIG_FILE.read_text())
    else:
        log.warning("tools_config.json not found at %s — skipping upload", _CONFIG_FILE)

    if _PROMPT_FILE.exists():
        log.info("Uploading prompt.txt → %s", prompt_gcs_uri)
        write_gcs_text(prompt_gcs_uri, _PROMPT_FILE.read_text())
    else:
        log.warning("prompt.txt not found at %s — skipping upload", _PROMPT_FILE)

    log.info("Phase 2 complete.")
    return {"tools_config_gcs_uri": config_gcs_uri, "prompt_gcs_uri": prompt_gcs_uri}


def phase3_deploy_agent(project: str, location: str, staging_bucket: str,
                         gcs_uris: dict[str, str]) -> str:
    log.info("── Phase 3: Agent Engine Deployment ──")
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE)

    import vertexai
    from vertexai import agent_engines
    from vertexai.preview.reasoning_engines import AdkApp

    vertexai.init(project=project, location=location, staging_bucket=staging_bucket)

    from agent import app as adk_app
    wrapped = AdkApp(agent=adk_app, enable_tracing=True)

    agent_env_vars: dict[str, str] = {"GOOGLE_GENAI_USE_VERTEXAI": "1"}
    for key in ["TOOLS_CONFIG_GCS_URI", "PROMPT_GCS_URI", "FIRESTORE_USAGE_COLLECTION",
                "EMAIL_MCP_URL", "ALERT_TO_EMAILS", "ALERT_FROM_NAME", "EMAIL_AGENT_RESOURCE_NAME"]:
        val = os.getenv(key, "")
        if val:
            agent_env_vars[key] = val
    if gcs_uris.get("tools_config_gcs_uri"):
        agent_env_vars["TOOLS_CONFIG_GCS_URI"] = gcs_uris["tools_config_gcs_uri"]
    if gcs_uris.get("prompt_gcs_uri"):
        agent_env_vars["PROMPT_GCS_URI"] = gcs_uris["prompt_gcs_uri"]

    # Temporarily copy tools/ into OpsIQ/ for bundling
    _tools_local = _AGENT_ROOT / "tools"
    try:
        shutil.copytree(_TOOLS_SRC, _tools_local, dirs_exist_ok=True)

        state = _load_state()
        existing_id = state.get("agent_engine") or os.environ.get("AGENT_ENGINE_ID", "")

        if existing_id:
            try:
                _existing = agent_engines.get(existing_id)
                remote_app = _existing.update(
                    agent_engine=wrapped,
                    requirements=_REQUIREMENTS,
                    env_vars=agent_env_vars,
                    extra_packages=["./OpsIQ", "./tools"],
                )
                log.info("Updated existing: %s", remote_app.resource_name)
            except Exception as upd_err:
                log.warning("Update failed (%s) — creating new", upd_err)
                remote_app = agent_engines.create(
                    wrapped,
                    display_name="Ops IQ — GCP Resource Monitor",
                    requirements=_REQUIREMENTS,
                    extra_packages=["./OpsIQ", "./tools"],
                    env_vars=agent_env_vars,
                )
        else:
            remote_app = agent_engines.create(
                wrapped,
                display_name="Ops IQ — GCP Resource Monitor",
                requirements=_REQUIREMENTS,
                extra_packages=["./OpsIQ", "./tools"],
                env_vars=agent_env_vars,
            )
    finally:
        if _tools_local.exists():
            shutil.rmtree(_tools_local)

    resource_name = remote_app.resource_name
    log.info("Deployed: %s", resource_name)
    log.info("Phase 3 complete.")
    return resource_name


def cmd_deploy(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE)

    project        = args.project or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location       = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    staging_bucket = args.staging_bucket or os.environ.get("STAGING_BUCKET", "")

    if not project:
        log.error("--project is required (or set GOOGLE_CLOUD_PROJECT in .env)")
        sys.exit(1)
    if not staging_bucket:
        log.error("--staging-bucket is required (or set STAGING_BUCKET in .env)")
        sys.exit(1)

    if not args.skip_infrastructure:
        phase1_infrastructure(project, staging_bucket)

    gcs_uris = phase2_upload_config(project)
    resource_name = phase3_deploy_agent(project, location, staging_bucket, gcs_uris)

    state = {**_load_state(), "agent_engine": resource_name, **gcs_uris}
    _save_state(state)
    log.info("State saved to %s", _STATE_FILE)

    try:
        from dotenv import set_key
        set_key(str(_ENV_FILE), "AGENT_ENGINE_ID", resource_name)
        set_key(str(_ENV_FILE), "OPS_IQ_RESOURCE_NAME", resource_name)
    except Exception as exc:
        log.warning("Could not update .env: %s", exc)

    log.info("✅ Deployment complete: %s", resource_name)


def cmd_delete(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE)

    project  = args.project or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    state = _load_state()
    resource_name = args.resource_id or state.get("agent_engine") or os.environ.get("AGENT_ENGINE_ID", "")

    if not resource_name:
        log.error("No resource ID found. Pass --resource-id or ensure deployment_state.json exists.")
        sys.exit(1)

    import vertexai
    from vertexai import agent_engines

    vertexai.init(project=project, location=location)
    log.info("Deleting Agent Engine: %s", resource_name)
    try:
        engine = agent_engines.get(resource_name)
        engine.delete(force=True)
        log.info("Deleted: %s", resource_name)
    except Exception as exc:
        log.error("Delete failed: %s", exc)
        sys.exit(1)

    state.pop("agent_engine", None)
    _save_state(state)
    log.info("✅ Teardown complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ops IQ deploy / teardown")
    parser.add_argument("--project", help="GCP project ID")
    parser.add_argument("--staging-bucket", help="GCS staging bucket for Vertex AI packaging")
    parser.add_argument("--skip-infrastructure", action="store_true",
                        help="Skip Phase 1 (API enablement + bucket check)")
    parser.add_argument("--delete", action="store_true", help="Teardown mode")
    parser.add_argument("--resource-id", help="(delete mode) explicit Agent Engine resource name")
    args = parser.parse_args()

    if args.delete:
        cmd_delete(args)
    else:
        cmd_deploy(args)


if __name__ == "__main__":
    main()
