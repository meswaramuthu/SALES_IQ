#!/usr/bin/env python3
"""
Knowledge IQ — Central deploy / teardown script.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEPLOY MODE  (default)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 1 — GCP Infrastructure
    • Enable required APIs
    • Create GCS staging + config bucket (idempotent)

Phase 2 — RAG Corpus
    • Create corpus with chosen embedding model (or reuse existing)
    • Optionally seed with documents from a GCS folder

Phase 3 — Dynamic Config Upload
    • Upload tools_config.json  → GCS (controls which tools are live)
    • Upload prompt.txt         → GCS (agent system prompt)

Phase 4 — Agent Engine Deployment
    • Install dependencies  (uv sync)
    • Build Python wheel
    • Deploy AdkApp to Vertex AI Agent Engine
    • Run smoke test

Phase 5 — Gemini Enterprise  (optional, --skip-gemini-enterprise to bypass)
    • Create OAuth 2.0 authorization resource  (if creds provided)
    • Create / reuse Gemini Enterprise app
    • Register agent
    • Grant IAM access to specified members

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DELETE MODE  (--delete)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Reads resource IDs from deployment_state.json (auto-populated on deploy).
Pass explicit --resource-id / --corpus to override.

Removes (in order):
    1. Vertex AI Agent Engine resource
    2. RAG corpus + all indexed files  (requires --delete-corpus flag)
    3. GCS config objects              (requires --delete-gcs-config flag)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Full deploy from agents/knowledge-iq/
  uv run python deployment/deploy_full.py --project ninth-archway-496404-s2

# Skip Gemini Enterprise integration
  uv run python deployment/deploy_full.py --project ninth-archway-496404-s2 \\
      --skip-gemini-enterprise

# Deploy, reuse an existing RAG corpus
  uv run python deployment/deploy_full.py --project ninth-archway-496404-s2 \\
      --corpus projects/528271267622/locations/us-central1/ragCorpora/123456789

# Deploy with initial document seed from GCS
  uv run python deployment/deploy_full.py --project ninth-archway-496404-s2 \\
      --seed-gcs gs://my-bucket/docs/

# Full teardown — Agent Engine + corpus + GCS config
  uv run python deployment/deploy_full.py --delete --project ninth-archway-496404-s2 \\
      --delete-corpus --delete-gcs-config

# Teardown specifying explicit resource IDs (skips reading state file)
  uv run python deployment/deploy_full.py --delete --project ninth-archway-496404-s2 \\
      --resource-id projects/528271267622/locations/us-central1/reasoningEngines/999 \\
      --corpus projects/528271267622/locations/us-central1/ragCorpora/123 \\
      --delete-corpus --delete-gcs-config
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests
import vertexai
from dotenv import load_dotenv, set_key
from google.api_core.exceptions import NotFound
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

_SCRIPT_DIR   = Path(__file__).parent.resolve()      # deployment/
_PROJECT_ROOT = _SCRIPT_DIR.parent.resolve()         # knowledge-iq/
_ENV_FILE     = _PROJECT_ROOT / ".env"
_STATE_FILE   = _SCRIPT_DIR / "deployment_state.json"
_CONFIG_FILE  = _PROJECT_ROOT / "config" / "tools_config.json"
_PROMPT_FILE  = _PROJECT_ROOT / "config" / "prompt.txt"

_REQUIREMENTS = [
    "google-cloud-aiplatform[adk,agent-engines]==1.153.1",  # pin: 1.154+ calls Runner.run(state_delta=) which adk 1.x doesn't support
    "google-adk==1.34.3",  # pin: latest 1.x compatible with aiplatform 1.153.1
    "python-dotenv",
    "google-cloud-storage>=2.0",
    "google-auth>=2.36.0",
    "google-auth-httplib2>=0.2.0",
    "google-auth-oauthlib>=1.2.0",
    "google-api-python-client>=2.0",
    "PyGithub>=2.0",
    "atlassian-python-api>=3.41.0",
    "beautifulsoup4>=4.12.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.8.1",
    "requests>=2.32.3",
    "msal>=1.20.0",
]

DISCOVERY_ENGINE_BASE = "https://us-discoveryengine.googleapis.com"

# ── State helpers ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    return json.loads(_STATE_FILE.read_text()) if _STATE_FILE.exists() else {}


def _save_state(state: dict) -> None:
    _STATE_FILE.write_text(json.dumps(state, indent=2))
    log.info("State saved → %s", _STATE_FILE)


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

    # Grant Agent Engine SA the permissions it needs at runtime:
    #   - aiplatform.user       : read/write RAG corpora and files
    #   - storage.objectViewer  : read GCS source files when importing documents
    #   - storage.objectAdmin   : write user_file_registry.json + stage files for rag.upload_file()
    re_sa = f"serviceAccount:service-{_project_number_from_gcloud(project)}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
    for role in ("roles/aiplatform.user", "roles/storage.objectViewer"):
        _sh([
            "gcloud", "projects", "add-iam-policy-binding", project,
            "--member", re_sa,
            "--role", role,
            "--condition=None",
        ], check=False)
    # Grant objectAdmin on the knowledge-iq bucket specifically (not project-wide)
    # so the SA can write user_file_registry.json and stage upload files.
    _sh([
        "gcloud", "storage", "buckets", "add-iam-policy-binding",
        f"gs://{bucket_name}",
        "--member", re_sa,
        "--role", "roles/storage.objectAdmin",
    ], check=False)
    log.info("Agent Engine SA IAM roles ensured.")

    return bucket_uri


def _project_number_from_gcloud(project_id: str) -> str:
    result = subprocess.run(
        ["gcloud", "projects", "describe", project_id, "--format=value(projectNumber)"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — RAG Corpus
# ─────────────────────────────────────────────────────────────────────────────

def phase2_rag_corpus(
    project: str,
    location: str,
    rag_location: str,
    corpus_name: str,
    corpus_display_name: str,
    embedding_model: str,
    seed_gcs: str,
    chunk_size: int,
    chunk_overlap: int,
) -> str:
    """Create or reuse a RAG corpus. Returns the corpus resource name."""
    log.info("")
    log.info("━━  Phase 2 › RAG Corpus  ━━")

    from vertexai.preview import rag

    if corpus_name:
        # Validate the provided corpus exists
        try:
            existing = rag.get_corpus(name=corpus_name)
            log.info("Using existing corpus: %s  (%s)", existing.display_name, corpus_name)
            return corpus_name
        except NotFound:
            log.error("Corpus not found: %s", corpus_name)
            sys.exit(1)

    # Look for existing corpus with same display name
    for c in rag.list_corpora():
        if c.display_name == corpus_display_name:
            log.info("Found existing corpus '%s': %s", corpus_display_name, c.name)
            corpus_name = c.name
            break

    if not corpus_name:
        log.info("Creating corpus '%s' with model '%s' (Serverless/KNN mode) …", corpus_display_name, embedding_model)
        # Use the Gapic client directly: the high-level rag.create_corpus() sets the
        # deprecated vector_db_config field (Spanner), not rag_vector_db_config (Serverless).
        from google.cloud.aiplatform_v1beta1.types import (  # noqa: PLC0415
            CreateRagCorpusRequest,
            RagCorpus as GapicRagCorpus,
            RagVectorDbConfig as GapicRagVectorDbConfig,
        )
        from vertexai.preview.rag.utils._gapic_utils import (  # noqa: PLC0415
            convert_gapic_to_rag_corpus,
            create_rag_data_service_client,
        )
        gapic_corpus = GapicRagCorpus(
            display_name=corpus_display_name,
            description=f"Knowledge IQ corpus — {corpus_display_name}",
            rag_vector_db_config=GapicRagVectorDbConfig(
                rag_managed_db=GapicRagVectorDbConfig.RagManagedDb(
                    knn=GapicRagVectorDbConfig.RagManagedDb.KNN()
                )
            ),
        )
        # Use rag_location for the corpus — us-central1 is blocked for new projects
        parent = f"projects/{project}/locations/{rag_location}"
        request = CreateRagCorpusRequest(parent=parent, rag_corpus=gapic_corpus)
        import vertexai as _vx  # noqa: PLC0415
        _vx.init(project=project, location=rag_location)
        client = create_rag_data_service_client()
        try:
            operation = client.create_rag_corpus(request=request)
            result = operation.result(timeout=600)
        except Exception as exc:
            raise RuntimeError("Failed to create RAG corpus", exc) from exc
        corpus_obj = convert_gapic_to_rag_corpus(result)
        corpus_name = corpus_obj.name
        log.info("Corpus created: %s", corpus_name)

    if seed_gcs:
        log.info("Seeding corpus from GCS: %s  (chunk_size=%d, overlap=%d)", seed_gcs, chunk_size, chunk_overlap)
        response = rag.import_files(
            corpus_name=corpus_name,
            paths=[seed_gcs],
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        log.info(
            "Seeding complete — imported: %d | failed: %d",
            response.imported_rag_files_count,
            response.failed_rag_files_count,
        )

    return corpus_name


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — Dynamic Config Upload
# ─────────────────────────────────────────────────────────────────────────────

def phase3_upload_config(
    corpus_name: str,
    bucket_name: str,
    tools_config_gcs_uri: str,
    prompt_gcs_uri: str,
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[str, str, dict]:
    """Upload tools_config.json and prompt.txt to GCS. Returns (config_uri, prompt_uri, config_data)."""
    log.info("")
    log.info("━━  Phase 3 › Dynamic Config Upload  ━━")

    from google.cloud import storage

    client = storage.Client()
    config_uri = tools_config_gcs_uri or f"gs://{bucket_name}/knowledge-iq/tools_config.json"
    prompt_uri = prompt_gcs_uri or f"gs://{bucket_name}/knowledge-iq/prompt.txt"

    # ── tools_config.json ──────────────────────────────────────────────────────
    # Use existing file if present, otherwise generate a minimal default.
    if _CONFIG_FILE.exists():
        log.info("Loading config from %s", _CONFIG_FILE)
        config_data = json.loads(_CONFIG_FILE.read_text())
    else:
        log.info("config/tools_config.json not found — generating default (RAG only).")
        config_data = _default_tools_config(corpus_name, embedding_model, chunk_size, chunk_overlap)

    # Ensure the corpus from Phase 2 is written into the config
    config_data.setdefault("tools", {}).setdefault("rag", {}).setdefault("config", {})
    if corpus_name:
        config_data["tools"]["rag"]["config"]["corpus"] = corpus_name
        config_data["tools"]["rag"]["enabled"] = True
    if not config_data["tools"]["rag"]["config"].get("embedding_model"):
        config_data["tools"]["rag"]["config"]["embedding_model"] = embedding_model
    if not config_data["tools"]["rag"]["config"].get("chunk_size"):
        config_data["tools"]["rag"]["config"]["chunk_size"] = chunk_size
    if not config_data["tools"]["rag"]["config"].get("chunk_overlap"):
        config_data["tools"]["rag"]["config"]["chunk_overlap"] = chunk_overlap

    _upload_text(client, config_uri, json.dumps(config_data, indent=2), "application/json")
    log.info("tools_config.json uploaded → %s", config_uri)

    # ── prompt.txt ─────────────────────────────────────────────────────────────
    if _PROMPT_FILE.exists():
        log.info("Loading prompt from %s", _PROMPT_FILE)
        prompt_text = _PROMPT_FILE.read_text()
    else:
        log.info("config/prompt.txt not found — using built-in default prompt.")
        prompt_text = ""  # agent falls back to built-in default

    if prompt_text:
        _upload_text(client, prompt_uri, prompt_text, "text/plain")
        log.info("prompt.txt uploaded → %s", prompt_uri)
    else:
        log.info("No custom prompt — agent will use its built-in default.")
        prompt_uri = ""

    return config_uri, prompt_uri, config_data


def _default_tools_config(
    corpus_name: str,
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
) -> dict:
    return {
        "tools": {
            "rag": {
                "enabled": bool(corpus_name),
                "config": {
                    "corpus": corpus_name,
                    "embedding_model": embedding_model,
                    "chunk_size": chunk_size,
                    "chunk_overlap": chunk_overlap,
                    "similarity_top_k": 10,
                    "vector_distance_threshold": 0.6,
                },
            },
            "gmail":      {"enabled": False, "config": {}},
            "gdrive":     {"enabled": False, "config": {}},
            "github":     {"enabled": False, "config": {}},
            "jira":       {"enabled": False, "config": {}},
            "confluence": {"enabled": False, "config": {}},
        }
    }


def _upload_text(client, gcs_uri: str, content: str, content_type: str) -> None:
    import re
    m = re.match(r"gs://([^/]+)/(.+)", gcs_uri)
    if not m:
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
    client.bucket(m.group(1)).blob(m.group(2)).upload_from_string(content, content_type=content_type)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — Agent Engine Deployment
# ─────────────────────────────────────────────────────────────────────────────

def phase4_deploy_agent(
    project: str,
    location: str,
    bucket_uri: str,
    tools_config_uri: str,
    prompt_uri: str,
    tools_config_data: dict | None = None,
) -> str:
    """Package source dir and deploy to Vertex AI Agent Engine. Returns resource name."""
    log.info("")
    log.info("━━  Phase 4 › Agent Engine Deployment  ━━")

    # Install deps
    log.info("Installing dependencies …")
    _sh(["uv", "sync"], cwd=_PROJECT_ROOT)

    # Run from project root so ./knowledge_iq path resolves correctly
    os.chdir(_PROJECT_ROOT)
    sys.path.insert(0, str(_PROJECT_ROOT))

    vertexai.init(project=project, location=location, staging_bucket=bucket_uri)

    from knowledge_iq.agent import root_agent  # noqa: PLC0415

    wrapped = AdkApp(agent=root_agent, enable_tracing=True)

    # ── Collect env vars for the remote agent ─────────────────────────────────
    # Note: GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION are reserved by Agent Engine
    agent_env_vars: dict[str, str] = {
        "GOOGLE_GENAI_USE_VERTEXAI": "1",
    }
    if tools_config_uri:
        agent_env_vars["TOOLS_CONFIG_GCS_URI"] = tools_config_uri
    if prompt_uri:
        agent_env_vars["PROMPT_GCS_URI"] = prompt_uri

    registry_uri = os.environ.get("USER_FILE_REGISTRY_URI", "")
    if registry_uri:
        agent_env_vars["USER_FILE_REGISTRY_URI"] = registry_uri

    # Auto-extract all "env:XXX" references from tools_config and pass resolved values
    for tool_cfg in (tools_config_data or {}).get("tools", {}).values():
        for value in tool_cfg.get("config", {}).values():
            if isinstance(value, str) and value.startswith("env:"):
                env_key = value[4:]
                env_val = os.environ.get(env_key, "")
                if env_val:
                    agent_env_vars[env_key] = env_val

    log.info("Passing env vars to remote agent: %s", list(agent_env_vars.keys()))

    # Copy stratova_shared into the project root so it can be bundled as a plain
    # Python package directory alongside knowledge_iq (same approach as deploy.py).
    _shared_src = _PROJECT_ROOT.parent / "shared" / "stratova_shared"
    _shared_local = _PROJECT_ROOT / "stratova_shared"
    shutil.copytree(_shared_src, _shared_local, dirs_exist_ok=True)
    log.info("Copied stratova_shared → %s for bundling", _shared_local)

    log.info("Deploying to Vertex AI Agent Engine (this takes 3–6 min) …")
    try:
        remote_app = agent_engines.create(
            wrapped,
            requirements=_REQUIREMENTS,
            extra_packages=["./knowledge_iq", "./stratova_shared"],
            env_vars=agent_env_vars,
        )
    finally:
        if _shared_local.exists():
            shutil.rmtree(_shared_local)
            log.info("Cleaned up temporary stratova_shared bundle")
    resource_name: str = remote_app.resource_name
    log.info("Agent Engine created: %s", resource_name)

    # Persist to .env
    try:
        set_key(str(_ENV_FILE), "AGENT_ENGINE_ID", resource_name)
        if tools_config_uri:
            set_key(str(_ENV_FILE), "TOOLS_CONFIG_GCS_URI", tools_config_uri)
        if prompt_uri:
            set_key(str(_ENV_FILE), "PROMPT_GCS_URI", prompt_uri)
        log.info("Updated .env with new resource IDs.")
    except Exception as exc:
        log.warning("Could not update .env: %s", exc)

    # Smoke test
    log.info("Running smoke test …")
    try:
        session = remote_app.create_session(user_id="smoke-test")
        responded = False
        for event in remote_app.stream_query(
            session_id=session["id"],
            message="Which data sources are you connected to?",
            user_id="smoke-test",
        ):
            if event.get("content"):
                log.info("Smoke test passed — agent is live.")
                responded = True
                break
        if not responded:
            log.warning("Smoke test got no response — check the agent manually.")
    except Exception as exc:
        log.warning("Smoke test error (agent may still be starting up): %s", exc)

    return resource_name


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 5 — Gemini Enterprise  (optional)
# ─────────────────────────────────────────────────────────────────────────────

def phase5_gemini_enterprise(
    project: str,
    location: str,
    resource_name: str,
    app_id: str,
    app_name: str,
    oauth_client_id: str,
    oauth_client_secret: str,
    grant_access: list[str],
) -> tuple[str, str]:
    """Register agent in Gemini Enterprise. Returns (app_id, agent_id)."""
    log.info("")
    log.info("━━  Phase 5 › Gemini Enterprise  ━━")

    token          = _access_token()
    project_number = _project_number(project, token)

    auth_resource: str | None = None
    if oauth_client_id and oauth_client_secret:
        auth_resource = _create_oauth_resource(
            project_number=project_number,
            auth_id="knowledge-iq-oauth",
            client_id=oauth_client_id,
            client_secret=oauth_client_secret,
            token=token,
        )
    else:
        log.warning(
            "No OAuth credentials — registering without authorization config.\n"
            "  Re-run with --oauth-client-id / --oauth-client-secret to add later."
        )

    app_id = _create_gemini_app(
        project_id=project,
        app_id=app_id,
        app_display_name=app_name,
        token=token,
        project_number=project_number,
    )

    agent_id = _register_agent(
        project_id=project,
        project_number=project_number,
        app_id=app_id,
        resource_name=resource_name,
        display_name="Knowledge IQ",
        description=(
            "Enterprise knowledge assistant that searches across Vertex AI RAG, "
            "Gmail, Google Drive, GitHub, Jira, and Confluence with dynamic "
            "tool enable/disable and runtime prompt management."
        ),
        auth_resource=auth_resource,
        token=token,
    )

    if grant_access:
        _grant_iam(project, grant_access)

    return app_id, agent_id


def _create_oauth_resource(
    project_number: str,
    auth_id: str,
    client_id: str,
    client_secret: str,
    token: str,
    location: str = "global",
) -> str:
    url = (
        f"{DISCOVERY_ENGINE_BASE}/v1alpha/"
        f"projects/{project_number}/locations/{location}"
        f"/authorizations?authorizationId={auth_id}"
    )
    body = {
        "name": f"projects/{project_number}/locations/{location}/authorizations/{auth_id}",
        "serverSideOauth2": {
            "clientId": client_id,
            "clientSecret": client_secret,
            "authorizationUri": "https://accounts.google.com/o/oauth2/auth",
            "tokenUri": "https://oauth2.googleapis.com/token",
        },
    }
    resp = requests.post(url, headers=_disc_headers(token, project_number), json=body, timeout=30)
    if resp.status_code == 409:
        log.info("OAuth resource '%s' already exists.", auth_id)
    else:
        resp.raise_for_status()
        log.info("OAuth resource created: %s", auth_id)
    return f"projects/{project_number}/locations/{location}/authorizations/{auth_id}"


def _create_gemini_app(
    project_id: str,
    app_id: str,
    app_display_name: str,
    token: str,
    project_number: str,
) -> str:
    url = (
        f"https://discoveryengine.googleapis.com/v1/projects/{project_id}"
        f"/locations/global/collections/default_collection/engines"
        f"?engineId={app_id}"
    )
    body = {
        "displayName": app_display_name,
        "solutionType": "SOLUTION_TYPE_CHAT",
        "industryVertical": "GENERIC",
        "appType": "APP_TYPE_INTRANET",
        "chatEngineConfig": {"agentCreationConfig": {}},
    }
    resp = requests.post(url, headers=_disc_headers(token, project_number), json=body, timeout=30)
    if resp.status_code == 409:
        log.info("Gemini Enterprise app '%s' already exists.", app_id)
    else:
        resp.raise_for_status()
        log.info("Gemini Enterprise app created: %s — waiting for propagation …", app_id)
        time.sleep(15)
    return app_id


def _register_agent(
    project_id: str,
    project_number: str,
    app_id: str,
    resource_name: str,
    display_name: str,
    description: str,
    auth_resource: str | None,
    token: str,
    location: str = "global",
) -> str:
    url = (
        f"{DISCOVERY_ENGINE_BASE}/v1alpha/projects/{project_id}"
        f"/locations/{location}/collections/default_collection"
        f"/engines/{app_id}/assistants/default_assistant/agents"
    )
    body: dict = {
        "displayName": display_name,
        "description": description,
        "adkAgentDefinition": {
            "provisionedReasoningEngine": {"reasoningEngine": resource_name}
        },
    }
    if auth_resource:
        body["authorizationConfig"] = {"toolAuthorizations": [auth_resource]}

    resp = requests.post(url, headers=_disc_headers(token, project_number), json=body, timeout=30)
    resp.raise_for_status()
    agent_id: str = resp.json().get("name", "")
    log.info("Agent registered in Gemini Enterprise: %s", agent_id)
    return agent_id


def _grant_iam(project: str, members: list[str]) -> None:
    log.info("Granting IAM access to %d member(s) …", len(members))
    for member in members:
        _sh([
            "gcloud", "projects", "add-iam-policy-binding", project,
            "--member", member,
            "--role", "roles/cloudaicompanion.user",
            "--condition=None",
        ])
        log.info("  Granted → %s", member)


# ─────────────────────────────────────────────────────────────────────────────
# DELETE MODE
# ─────────────────────────────────────────────────────────────────────────────

def delete_all(
    project: str,
    location: str,
    resource_id: str,
    corpus: str,
    do_delete_corpus: bool,
    do_delete_gcs_config: bool,
) -> None:
    log.info("")
    log.info("━━  DELETE MODE  ━━")

    state = _load_state()

    # Resolve resource IDs — explicit args override state file
    agent_resource = resource_id or state.get("agent_engine", "")
    corpus_resource = corpus or state.get("rag_corpus", "")
    config_uri  = state.get("tools_config_gcs_uri", "")
    prompt_uri  = state.get("prompt_gcs_uri", "")

    vertexai.init(project=project, location=location)

    # 1 ── Agent Engine
    if agent_resource:
        log.info("Deleting Agent Engine: %s", agent_resource)
        try:
            agent_engines.delete(resource_name=agent_resource, force=True)
            log.info("  Agent Engine deleted.")
        except NotFound:
            log.warning("  Agent Engine not found (already deleted?): %s", agent_resource)
    else:
        log.warning("No Agent Engine resource ID found — skipping.")

    # 2 ── RAG Corpus
    if do_delete_corpus:
        if corpus_resource:
            log.info("Deleting RAG corpus: %s", corpus_resource)
            try:
                from vertexai.preview import rag  # noqa: PLC0415

                # Delete all files first
                files = list(rag.list_files(corpus_name=corpus_resource))
                if files:
                    log.info("  Deleting %d indexed file(s) …", len(files))
                    for f in files:
                        rag.delete_file(name=f.name)
                rag.delete_corpus(name=corpus_resource)
                log.info("  RAG corpus deleted.")
            except NotFound:
                log.warning("  Corpus not found (already deleted?): %s", corpus_resource)
            except Exception as exc:
                log.error("  Failed to delete corpus: %s", exc)
        else:
            log.warning("--delete-corpus specified but no corpus resource ID found — skipping.")

    # 3 ── GCS config objects
    if do_delete_gcs_config:
        for uri in filter(None, [config_uri, prompt_uri]):
            _delete_gcs_object(uri)

    # 4 ── Clean up state file
    if _STATE_FILE.exists():
        _STATE_FILE.unlink()
        log.info("Removed deployment_state.json.")

    log.info("")
    log.info("Teardown complete.")


def _delete_gcs_object(gcs_uri: str) -> None:
    import re
    m = re.match(r"gs://([^/]+)/(.+)", gcs_uri)
    if not m:
        log.warning("Invalid GCS URI — skipping: %s", gcs_uri)
        return
    try:
        from google.cloud import storage  # noqa: PLC0415

        client = storage.Client()
        blob = client.bucket(m.group(1)).blob(m.group(2))
        blob.delete()
        log.info("  Deleted GCS object: %s", gcs_uri)
    except NotFound:
        log.warning("  GCS object not found: %s", gcs_uri)
    except Exception as exc:
        log.error("  Failed to delete %s: %s", gcs_uri, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Summary printer
# ─────────────────────────────────────────────────────────────────────────────

def _print_summary(state: dict) -> None:
    log.info("")
    log.info("═" * 65)
    log.info("  Knowledge IQ — Deployment complete!")
    log.info("  Agent Engine   : %s", state.get("agent_engine", "—"))
    log.info("  RAG corpus     : %s", state.get("rag_corpus", "—"))
    log.info("  Config GCS URI : %s", state.get("tools_config_gcs_uri", "—"))
    log.info("  Prompt GCS URI : %s", state.get("prompt_gcs_uri", "—"))
    if state.get("gemini_enterprise", {}).get("app_id"):
        log.info("  Gemini app     : %s", state["gemini_enterprise"]["app_id"])
        log.info("  Access at      : https://gemini.google.com/app")
    log.info("  State file     : %s", _STATE_FILE)
    log.info("")
    log.info("  Runtime operations (no redeploy needed):")
    log.info("    Enable/disable a tool → edit tools_config.json, run: make upload-config")
    log.info("    Change agent prompt   → edit config/prompt.txt,  run: make upload-prompt")
    log.info("    Add documents to RAG  → ask the agent: 'add document <url or gs://...'")
    log.info("═" * 65)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Knowledge IQ — central deploy / teardown script.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Core
    p.add_argument("--project",  default=os.getenv("GOOGLE_CLOUD_PROJECT", ""),      help="GCP project ID")
    p.add_argument("--location", default=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"), help="GCP region for Agent Engine (default: us-central1)")
    p.add_argument("--rag-location", default=os.getenv("RAG_LOCATION", "us-west1"),
                   help="GCP region for RAG corpus (default: us-west1 — us-central1 is blocked for new projects)")

    # Bucket
    p.add_argument("--bucket",
                   default=os.getenv("STAGING_BUCKET", "").lstrip("gs://"),
                   help="GCS bucket name (without gs://) used for staging, config, and prompt files. "
                        "Defaults to <project>-knowledge-iq.")

    # RAG
    p.add_argument("--corpus",
                   default=os.getenv("RAG_CORPUS", ""),
                   help="Existing RAG corpus resource name. If omitted a new one is created.")
    p.add_argument("--corpus-name",  default="Knowledge IQ Corpus",
                   help="Display name for a newly created corpus (default: 'Knowledge IQ Corpus')")
    p.add_argument("--embedding-model",
                   default=os.getenv("RAG_EMBEDDING_MODEL", "publishers/google/models/text-embedding-004"),
                   help="Embedding model for new corpus creation")
    p.add_argument("--seed-gcs",   default="", help="GCS path to seed the corpus on first deploy (e.g. gs://bucket/docs/)")
    p.add_argument("--chunk-size",    type=int, default=int(os.getenv("RAG_CHUNK_SIZE", "512")),    help="RAG chunk size (default 512)")
    p.add_argument("--chunk-overlap", type=int, default=int(os.getenv("RAG_CHUNK_OVERLAP", "100")), help="RAG chunk overlap (default 100)")

    # Dynamic config GCS URIs
    p.add_argument("--tools-config-gcs-uri", default=os.getenv("TOOLS_CONFIG_GCS_URI", ""),
                   help="GCS URI for tools_config.json. Defaults to gs://<bucket>/knowledge-iq/tools_config.json")
    p.add_argument("--prompt-gcs-uri",       default=os.getenv("PROMPT_GCS_URI", ""),
                   help="GCS URI for prompt.txt. Defaults to gs://<bucket>/knowledge-iq/prompt.txt")

    # Gemini Enterprise
    p.add_argument("--app-id",   default="knowledge-iq",        help="Gemini Enterprise app ID")
    p.add_argument("--app-name", default="Knowledge IQ",         help="Gemini Enterprise app display name")
    p.add_argument("--oauth-client-id",     default=os.getenv("OAUTH_CLIENT_ID", ""))
    p.add_argument("--oauth-client-secret", default=os.getenv("OAUTH_CLIENT_SECRET", ""))
    p.add_argument("--grant-access", nargs="*", metavar="MEMBER",
                   help="IAM members to grant access (e.g. user:you@domain.com)")

    # Skip flags
    p.add_argument("--skip-infrastructure", action="store_true",
                   help="Skip Phase 1 (API enablement + bucket check) — use when infra already exists")
    p.add_argument("--skip-gemini-enterprise", action="store_true",
                   help="Skip Gemini Enterprise integration (Agent Engine only)")

    # Delete mode
    p.add_argument("--delete",  action="store_true",
                   help="Teardown mode — delete the deployed agent and resources")
    p.add_argument("--resource-id", dest="resource_id", default="",
                   help="Agent Engine resource name for --delete (reads state file if omitted)")
    p.add_argument("--delete-corpus",     action="store_true",
                   help="Also delete the RAG corpus and all indexed files during teardown")
    p.add_argument("--delete-gcs-config", action="store_true",
                   help="Also delete tools_config.json and prompt.txt from GCS during teardown")

    return p.parse_args()


def main() -> None:
    load_dotenv(str(_ENV_FILE))
    args = _build_args()

    if not args.project:
        log.error("--project is required, or set GOOGLE_CLOUD_PROJECT in .env")
        sys.exit(1)

    # ── DELETE MODE ───────────────────────────────────────────────────────────
    if args.delete:
        delete_all(
            project=args.project,
            location=args.location,
            resource_id=args.resource_id,
            corpus=args.corpus,
            do_delete_corpus=args.delete_corpus,
            do_delete_gcs_config=args.delete_gcs_config,
        )
        return

    # ── DEPLOY MODE ───────────────────────────────────────────────────────────

    bucket_name = args.bucket or f"{args.project}-knowledge-iq"
    state: dict = {
        "project": args.project,
        "location": args.location,
    }

    # Phase 1 — Infrastructure
    if not args.skip_infrastructure:
        bucket_uri = phase1_infrastructure(args.project, args.location, bucket_name)
    else:
        bucket_uri = f"gs://{bucket_name}"
        log.info("Skipping Phase 1 (infrastructure already exists). Bucket: %s", bucket_uri)
    state["staging_bucket"] = bucket_uri

    # Phase 2 — RAG Corpus (uses rag_location — us-central1 is blocked for new projects)
    rag_location = args.rag_location
    log.info("RAG corpus location: %s  (Agent Engine location: %s)", rag_location, args.location)
    vertexai.init(project=args.project, location=rag_location, staging_bucket=bucket_uri)
    corpus_name = phase2_rag_corpus(
        project=args.project,
        location=args.location,
        rag_location=rag_location,
        corpus_name=args.corpus,
        corpus_display_name=args.corpus_name,
        embedding_model=args.embedding_model,
        seed_gcs=args.seed_gcs,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    state["rag_corpus"] = corpus_name
    state["rag_location"] = rag_location

    # Phase 3 — Upload Config
    config_uri, prompt_uri, config_data = phase3_upload_config(
        corpus_name=corpus_name,
        bucket_name=bucket_name,
        tools_config_gcs_uri=args.tools_config_gcs_uri,
        prompt_gcs_uri=args.prompt_gcs_uri,
        embedding_model=args.embedding_model,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    state["tools_config_gcs_uri"] = config_uri
    state["prompt_gcs_uri"] = prompt_uri

    # Phase 4 — Agent Engine (re-init vertexai to agent location; phase2 may have changed it)
    vertexai.init(project=args.project, location=args.location, staging_bucket=bucket_uri)
    resource_name = phase4_deploy_agent(
        project=args.project,
        location=args.location,
        bucket_uri=bucket_uri,
        tools_config_uri=config_uri,
        prompt_uri=prompt_uri,
        tools_config_data=config_data,
    )
    state["agent_engine"] = resource_name
    _save_state(state)

    # Phase 5 — Gemini Enterprise (optional)
    if not args.skip_gemini_enterprise:
        app_id, agent_id = phase5_gemini_enterprise(
            project=args.project,
            location=args.location,
            resource_name=resource_name,
            app_id=args.app_id,
            app_name=args.app_name,
            oauth_client_id=args.oauth_client_id,
            oauth_client_secret=args.oauth_client_secret,
            grant_access=args.grant_access or [],
        )
        state["gemini_enterprise"] = {"app_id": app_id, "agent_id": agent_id}
        _save_state(state)

    _print_summary(state)


if __name__ == "__main__":
    main()
