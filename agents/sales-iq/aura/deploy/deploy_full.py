#!/usr/bin/env python3
"""
AURA Sales IQ — Central deploy / teardown script.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEPLOY MODE  (default)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 1 — GCP Infrastructure
    • Enable required APIs
    • Create GCS staging + config bucket (idempotent)

Phase 2 — Dynamic Config Upload
    • Upload tools_config.json  → GCS (controls which tools are live)
    • Upload prompt.md          → GCS (AURA_orch system prompt)

Phase 3 — Agent Engine Deployment
    • Install dependencies  (uv sync)
    • Build Python wheel
    • Deploy AdkApp to Vertex AI Agent Engine
    • Run smoke test

Phase 4 — Gemini Enterprise  (optional, --skip-gemini-enterprise to bypass)
    • Create / reuse Gemini Enterprise app
    • Register AURA agent
    • Grant IAM access to specified members

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DELETE MODE  (--delete)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Reads resource IDs from deployment_state.json (auto-populated on deploy).
Pass explicit --resource-id to override.

Removes (in order):
    1. Vertex AI Agent Engine resource
    2. GCS config objects (requires --delete-gcs-config flag)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Full deploy
  uv run python deploy/deploy_full.py --project your-gcp-project-id

# Skip Gemini Enterprise integration
  uv run python deploy/deploy_full.py --project your-gcp-project-id \\
      --skip-gemini-enterprise

# Full teardown — Agent Engine + GCS config
  uv run python deploy/deploy_full.py --delete --project your-gcp-project-id \\
      --delete-gcs-config
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import vertexai
from dotenv import load_dotenv, set_key
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

_SCRIPT_DIR   = Path(__file__).parent.resolve()      # deploy/
_PROJECT_ROOT = _SCRIPT_DIR.parent.resolve()         # aura/
_REPO_ROOT    = _PROJECT_ROOT.parent.parent.parent   # laabu-ai-app/
_ENV_FILE     = _PROJECT_ROOT / ".env"
_STATE_FILE   = _SCRIPT_DIR / "deployment_state.json"
_CONFIG_FILE  = _PROJECT_ROOT / "AURA_orch" / "tools_config.json"
_PROMPT_FILE  = _PROJECT_ROOT / "AURA_orch" / "prompt.md"

_REQUIREMENTS = [
    "google-cloud-aiplatform[adk,agent-engines]==1.153.1",
    "google-adk==1.34.3",
    "python-dotenv",
    "google-cloud-storage>=2.0",
    "google-auth>=2.36.0",
    "google-auth-httplib2>=0.2.0",
    "google-auth-oauthlib>=1.2.0",
    "google-api-python-client>=2.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.8.1",
    "requests>=2.32.3",
    "msal>=1.20.0",
    "beautifulsoup4>=4.12.0",
]

DISCOVERY_ENGINE_BASE = "https://us-discoveryengine.googleapis.com"

# ── State helpers ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    return json.loads(_STATE_FILE.read_text()) if _STATE_FILE.exists() else {}


def _save_state(state: dict) -> None:
    _STATE_FILE.write_text(json.dumps(state, indent=2))
    log.info("State saved → %s", _STATE_FILE)


# ── Secret Manager helper ─────────────────────────────────────────────────────

def _save_to_secret_manager(project: str, secret_id: str, value: str) -> None:
    """Idempotently create-or-update a GCP Secret Manager secret. Best-effort."""
    try:
        from google.cloud import secretmanager  # noqa: PLC0415
        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project}"
        secret_path = f"{parent}/secrets/{secret_id}"
        try:
            client.get_secret(request={"name": secret_path})
        except Exception:
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_id,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
        client.add_secret_version(
            request={"parent": secret_path, "payload": {"data": value.encode()}}
        )
        log.info("[Secret Manager] Saved '%s'.", secret_id)
    except Exception as exc:
        log.warning("[Secret Manager] Could not save '%s' (non-fatal): %s", secret_id, exc)


# ── Shell helper ──────────────────────────────────────────────────────────────

def _sh(cmd: list[str], *, cwd: str | Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    log.info("$ %s", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=check, cwd=str(cwd) if cwd else None, text=True)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _access_token() -> str:
    creds, _ = google_auth_default()
    creds.refresh(GoogleAuthRequest())
    return creds.token  # type: ignore[union-attr]


def _project_number(project_id: str, token: str) -> str:
    r = requests.get(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return str(r.json()["projectNumber"])


def _disc_headers(token: str, project_number: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": project_number,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — GCP Infrastructure
# ─────────────────────────────────────────────────────────────────────────────

def phase1_infrastructure(project: str, location: str, bucket_name: str) -> str:
    log.info("")
    log.info("━━  Phase 1 › GCP Infrastructure  ━━")

    _sh([
        "gcloud", "services", "enable",
        "aiplatform.googleapis.com",
        "storage.googleapis.com",
        "cloudresourcemanager.googleapis.com",
        "iamcredentials.googleapis.com",
        "--project", project,
    ])
    log.info("Required APIs enabled.")

    bucket_uri = f"gs://{bucket_name}"
    result = _sh(
        ["gcloud", "storage", "buckets", "describe", bucket_uri, "--project", project],
        check=False,
    )
    if result.returncode != 0:
        log.info("Creating GCS bucket: %s", bucket_uri)
        _sh([
            "gcloud", "storage", "buckets", "create", bucket_uri,
            "--project", project,
            "--location", location,
            "--uniform-bucket-level-access",
        ])
    else:
        log.info("Bucket already exists: %s", bucket_uri)

    return bucket_uri


def _project_number_from_gcloud(project_id: str) -> str:
    result = subprocess.run(
        ["gcloud", "projects", "describe", project_id, "--format=value(projectNumber)"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — Dynamic Config Upload
# ─────────────────────────────────────────────────────────────────────────────

def phase2_upload_config(
    bucket_name: str,
    tools_config_gcs_uri: str,
    prompt_gcs_uri: str,
) -> tuple[str, str, dict]:
    """Upload tools_config.json and prompt.md to GCS. Returns (config_uri, prompt_uri, config_data)."""
    log.info("")
    log.info("━━  Phase 2 › Dynamic Config Upload  ━━")

    from google.cloud import storage

    client = storage.Client()
    config_uri = tools_config_gcs_uri or f"gs://{bucket_name}/sales-iq/tools_config.json"
    prompt_uri = prompt_gcs_uri or f"gs://{bucket_name}/sales-iq/prompt.md"

    # ── tools_config.json ──────────────────────────────────────────────────────
    if _CONFIG_FILE.exists():
        log.info("Loading config from %s", _CONFIG_FILE)
        config_data = json.loads(_CONFIG_FILE.read_text())
    else:
        log.warning("AURA_orch/tools_config.json not found — generating default config.")
        config_data = _default_tools_config()

    _upload_text(client, config_uri, json.dumps(config_data, indent=2), "application/json")
    log.info("tools_config.json uploaded → %s", config_uri)

    # ── prompt.md ─────────────────────────────────────────────────────────────
    if _PROMPT_FILE.exists():
        log.info("Loading prompt from %s", _PROMPT_FILE)
        prompt_text = _PROMPT_FILE.read_text()
    else:
        log.info("AURA_orch/prompt.md not found — agent will use built-in default.")
        prompt_text = ""

    if prompt_text:
        _upload_text(client, prompt_uri, prompt_text, "text/plain")
        log.info("prompt.md uploaded → %s", prompt_uri)
    else:
        log.info("No custom prompt — agent will use its built-in default.")
        prompt_uri = ""

    return config_uri, prompt_uri, config_data


def _default_tools_config() -> dict:
    return {
        "tools": {
            "crm":      {"enabled": False, "config": {}},
            "calendar": {"enabled": False, "config": {}},
            "gmail":    {"enabled": False, "config": {}},
            "gdrive":   {"enabled": False, "config": {}},
            "apollo":   {"enabled": False, "config": {}},
            "clearbit": {"enabled": False, "config": {}},
            "slack":    {"enabled": False, "config": {}},
        },
        "sub_agents": {
            "discovery_agent":    {"enabled": False, "resource_name": "", "description": "Lead discovery & ICP scoring"},
            "qualification_agent":{"enabled": False, "resource_name": "", "description": "BANT/MEDDIC qualification"},
            "booking_agent":      {"enabled": False, "resource_name": "", "description": "Meeting scheduling"},
            "proposal_agent":     {"enabled": False, "resource_name": "", "description": "Proposal generation"},
            "followup_agent":     {"enabled": False, "resource_name": "", "description": "Follow-up sequencing"},
            "revenue_agent":      {"enabled": False, "resource_name": "", "description": "Pipeline analytics"},
            "dealdesk_agent":     {"enabled": False, "resource_name": "", "description": "Deal structuring & approvals"},
        },
    }


def _upload_text(client, gcs_uri: str, content: str, content_type: str) -> None:
    import re
    m = re.match(r"gs://([^/]+)/(.+)", gcs_uri)
    if not m:
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
    client.bucket(m.group(1)).blob(m.group(2)).upload_from_string(content, content_type=content_type)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — Agent Engine Deployment
# ─────────────────────────────────────────────────────────────────────────────

def phase3_deploy_agent(
    project: str,
    location: str,
    bucket_uri: str,
    tools_config_uri: str,
    prompt_uri: str,
    tools_config_data: dict | None = None,
) -> str:
    """Package source dir and deploy to Vertex AI Agent Engine. Returns resource name."""
    log.info("")
    log.info("━━  Phase 3 › Agent Engine Deployment  ━━")

    log.info("Installing dependencies …")
    _sh(["uv", "sync"], cwd=_PROJECT_ROOT)

    os.chdir(_PROJECT_ROOT)
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_PROJECT_ROOT))

    vertexai.init(project=project, location=location, staging_bucket=bucket_uri)

    from agent import root_agent  # noqa: PLC0415

    wrapped = AdkApp(agent=root_agent, enable_tracing=True)

    agent_env_vars: dict[str, str] = {
        "GOOGLE_GENAI_USE_VERTEXAI": "1",
    }
    if tools_config_uri:
        agent_env_vars["TOOLS_CONFIG_GCS_URI"] = tools_config_uri
    if prompt_uri:
        agent_env_vars["PROMPT_GCS_URI"] = prompt_uri

    for tool_cfg in (tools_config_data or {}).get("tools", {}).values():
        for value in tool_cfg.get("config", {}).values():
            if isinstance(value, str) and value.startswith("env:"):
                env_key = value[4:]
                env_val = os.environ.get(env_key, "")
                if env_val:
                    agent_env_vars[env_key] = env_val

    log.info("Passing env vars to remote agent: %s", list(agent_env_vars.keys()))

    import importlib as _importlib
    import cloudpickle as _cloudpickle
    for _local_mod_name in ["prompts", "config", "agent"]:
        try:
            _mod = _importlib.import_module(_local_mod_name)
            _cloudpickle.register_pickle_by_value(_mod)
            log.info("Registered '%s' for by-value pickling.", _local_mod_name)
        except Exception as _e:
            log.warning("Could not register '%s' by value: %s", _local_mod_name, _e)

    import shutil
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory(prefix="aura_bundle_") as _tmp_bundle:
        _bundle = Path(_tmp_bundle)
        for _fname in ["agent.py", "config.py", "prompts.py"]:
            _src = _PROJECT_ROOT / _fname
            if _src.exists():
                shutil.copy2(_src, _bundle / _fname)
                log.info("Bundled flat file: %s", _fname)
        shutil.copytree(str(_REPO_ROOT / "tools"), str(_bundle / "tools"))
        log.info("Bundled: tools/")

        os.chdir(_bundle)
        log.info("extra_packages: [.]  (bundle → %s)", _bundle)

        _display_name = "AURA Sales IQ — Revenue Accelerator (Laabu)"
        _deploy_kwargs = dict(
            requirements=_REQUIREMENTS,
            extra_packages=["."],
            env_vars=agent_env_vars,
        )

        _existing_id = os.environ.get("AGENT_ENGINE_ID", "")
        if not _existing_id and _STATE_FILE.exists():
            _existing_id = _load_state().get("agent_engine", "")

        log.info("Deploying AURA to Vertex AI Agent Engine (this takes 3–6 min) …")
        if _existing_id:
            log.info("Existing agent found (%s) — updating in place …", _existing_id)
            try:
                _existing_app = agent_engines.get(_existing_id)
                remote_app = _existing_app.update(agent_engine=wrapped, **_deploy_kwargs)
                log.info("Agent Engine updated: %s", remote_app.resource_name)
            except Exception as _upd_err:
                log.warning("Update failed (%s) — falling back to create …", _upd_err)
                remote_app = agent_engines.create(
                    wrapped,
                    display_name=_display_name,
                    **_deploy_kwargs,
                )
                log.info("Agent Engine created: %s", remote_app.resource_name)
        else:
            log.info("No existing agent found — creating new …")
            remote_app = agent_engines.create(
                wrapped,
                display_name=_display_name,
                **_deploy_kwargs,
            )
            log.info("Agent Engine created: %s", remote_app.resource_name)

    resource_name: str = remote_app.resource_name

    try:
        set_key(str(_ENV_FILE), "AGENT_ENGINE_ID", resource_name)
        if tools_config_uri:
            set_key(str(_ENV_FILE), "TOOLS_CONFIG_GCS_URI", tools_config_uri)
        if prompt_uri:
            set_key(str(_ENV_FILE), "PROMPT_GCS_URI", prompt_uri)
        log.info("Updated .env with new resource IDs.")
    except Exception as exc:
        log.warning("Could not update .env: %s", exc)

    _save_to_secret_manager(project, "laabu-agents-sales-iq-engine-id", resource_name)

    log.info("Running smoke test …")
    try:
        session = remote_app.create_session(user_id="smoke-test")
        responded = False
        for event in remote_app.stream_query(
            session_id=session["id"],
            message="Which sales tools are you connected to?",
            user_id="smoke-test",
        ):
            if event.get("content"):
                log.info("Smoke test passed — AURA is live.")
                responded = True
                break
        if not responded:
            log.warning("Smoke test got no response — check the agent manually.")
    except Exception as exc:
        log.warning("Smoke test error (agent may still be starting up): %s", exc)

    return resource_name


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv(_ENV_FILE)

    parser = argparse.ArgumentParser(description="Deploy or delete AURA Sales IQ on Vertex AI Agent Engine.")
    parser.add_argument("--project",           default=os.environ.get("GOOGLE_CLOUD_PROJECT"), help="GCP project ID")
    parser.add_argument("--location",          default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    parser.add_argument("--bucket",            default=os.environ.get("STAGING_BUCKET", "").lstrip("gs://"))
    parser.add_argument("--tools-config-uri",  default=os.environ.get("TOOLS_CONFIG_GCS_URI", ""))
    parser.add_argument("--prompt-uri",        default=os.environ.get("PROMPT_GCS_URI", ""))
    parser.add_argument("--delete",            action="store_true")
    parser.add_argument("--delete-gcs-config", action="store_true")
    parser.add_argument("--resource-id",       default="")
    parser.add_argument("--skip-gemini-enterprise", action="store_true")
    args = parser.parse_args()

    if not args.project:
        parser.error("--project is required (or set GOOGLE_CLOUD_PROJECT)")

    bucket_name = args.bucket or f"{args.project}-sales-iq"

    if args.delete:
        resource_id = args.resource_id or _load_state().get("agent_engine", os.environ.get("AGENT_ENGINE_ID", ""))
        if not resource_id:
            log.error("No resource ID found. Provide --resource-id or ensure AGENT_ENGINE_ID is set.")
            sys.exit(1)
        vertexai.init(project=args.project, location=args.location)
        log.info("Deleting agent engine: %s", resource_id)
        agent_engines.get(resource_id).delete()
        log.info("Agent Engine deleted.")
        return

    # DEPLOY MODE
    bucket_uri = phase1_infrastructure(args.project, args.location, bucket_name)
    config_uri, prompt_uri, config_data = phase2_upload_config(
        bucket_name, args.tools_config_uri, args.prompt_uri
    )
    resource_name = phase3_deploy_agent(
        args.project, args.location, bucket_uri,
        config_uri, prompt_uri, config_data,
    )

    state = _load_state()
    state["agent_engine"] = resource_name
    state["project"] = args.project
    state["location"] = args.location
    _save_state(state)

    log.info("")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("AURA Sales IQ deployed successfully!")
    log.info("Resource: %s", resource_name)
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


if __name__ == "__main__":
    main()
