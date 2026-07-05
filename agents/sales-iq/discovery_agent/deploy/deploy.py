"""Deploy Knowledge IQ to Vertex AI Agent Engine."""
import json
import logging
import os
import shutil
import sys
import tomllib
from pathlib import Path

import vertexai
from dotenv import load_dotenv, set_key
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

# ── Paths ─────────────────────────────────────────────────────────────────────

_SCRIPT_DIR   = Path(__file__).parent.resolve()      # deploy/
_PROJECT_ROOT = _SCRIPT_DIR.parent.resolve()         # enterpriseGPT/
_REPO_ROOT    = _PROJECT_ROOT.parent.parent.parent   # laabu-ai-app/
_ENV_FILE     = _PROJECT_ROOT / ".env"

load_dotenv(_ENV_FILE)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.getenv("STAGING_BUCKET")

REQUIREMENTS = [
    "google-cloud-aiplatform[adk,agent-engines]==1.153.1",  # pin: 1.154+ calls Runner.run(state_delta=) which adk 1.x doesn't support
    "google-adk==1.34.3",
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

# ── Shared helper — locate stratova_shared source ─────────────────────────────

def _get_stratova_shared_src() -> Path:
    """Return path to the stratova_shared package directory (reads pyproject.toml)."""
    try:
        with open(_PROJECT_ROOT / "pyproject.toml", "rb") as f:
            toml = tomllib.load(f)
        raw = toml["tool"]["uv"]["sources"]["stratova-shared"]["path"]
        src = Path(raw) / "stratova_shared"
        if src.exists():
            return src
        # path may be relative to _PROJECT_ROOT
        src = (_PROJECT_ROOT / raw / "stratova_shared").resolve()
        if src.exists():
            return src
    except Exception as exc:
        logger.warning("Could not read stratova_shared path from pyproject.toml: %s", exc)
    fallback = _PROJECT_ROOT / "stratova_shared"
    if fallback.exists():
        return fallback
    raise RuntimeError(
        "Cannot locate stratova_shared source. "
        "Check pyproject.toml [tool.uv.sources] or ensure the stratova-gcp repo is checked out."
    )

# ── sys.path so agent.py / config.py / tools/ are importable ─────────────────

sys.path.insert(0, str(_REPO_ROOT))    # for tools/ package at repo root
sys.path.insert(0, str(_PROJECT_ROOT)) # for agent.py, config.py, prompts.py

from stratova_shared.session_service import build_resilient_session_service  # noqa: E402
from agent import app as adk_app  # noqa: E402  (agent.py is at _PROJECT_ROOT)

vertexai.init(
    project=GOOGLE_CLOUD_PROJECT,
    location=GOOGLE_CLOUD_LOCATION,
    staging_bucket=STAGING_BUCKET,
)

wrapped = AdkApp(agent=adk_app, enable_tracing=True, session_service_builder=build_resilient_session_service)

# ── Collect env vars for the remote agent ─────────────────────────────────────
agent_env_vars: dict[str, str] = {
    "GOOGLE_GENAI_USE_VERTEXAI": "1",
}

tools_config_uri = os.getenv("TOOLS_CONFIG_GCS_URI", "")
if tools_config_uri:
    agent_env_vars["TOOLS_CONFIG_GCS_URI"] = tools_config_uri

prompt_uri = os.getenv("PROMPT_GCS_URI", "")
if prompt_uri:
    agent_env_vars["PROMPT_GCS_URI"] = prompt_uri

registry_uri = os.getenv("USER_FILE_REGISTRY_URI", "")
if registry_uri:
    agent_env_vars["USER_FILE_REGISTRY_URI"] = registry_uri

# Auto-forward every secret referenced as "env:XXX" in the local tools_config.json
_config_path = _PROJECT_ROOT / "config" / "tools_config.json"
if _config_path.exists():
    _config_data = json.loads(_config_path.read_text())
    for tool_cfg in _config_data.get("tools", {}).values():
        for value in tool_cfg.get("config", {}).values():
            if isinstance(value, str) and value.startswith("env:"):
                env_key = value[4:]
                env_val = os.environ.get(env_key, "")
                if env_val:
                    agent_env_vars[env_key] = env_val

logger.info("Passing env vars to remote agent: %s", list(agent_env_vars.keys()))
logger.info("Deploying Knowledge IQ agent to %s / %s …", GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION)

# ── Bundle stratova_shared and tools/ alongside the agent wheel ───────────────

_shared_src   = _get_stratova_shared_src()
_shared_local = _PROJECT_ROOT / "stratova_shared"
_tools_local  = _PROJECT_ROOT / "tools"

try:
    shutil.copytree(_shared_src, _shared_local, dirs_exist_ok=True)
    shutil.copytree(_REPO_ROOT / "tools", _tools_local, dirs_exist_ok=True)
    logger.info("Copied stratova_shared → %s", _shared_local)
    logger.info("Copied tools/ → %s", _tools_local)

    existing_id = os.environ.get("AGENT_ENGINE_ID", "")
    if existing_id:
        try:
            _existing = agent_engines.get(existing_id)
            remote_app = _existing.update(
                agent_engine=wrapped,
                requirements=REQUIREMENTS,
                extra_packages=["./stratova_shared", "./tools"],
                env_vars=agent_env_vars,
            )
            logger.info("Updated existing: %s", remote_app.resource_name)
        except Exception as _upd_err:
            logger.warning("Update failed (%s) — creating new", _upd_err)
            remote_app = agent_engines.create(
                wrapped,
                display_name="KnowledgeIQ — Data Gateway (Laabu)",
                requirements=REQUIREMENTS,
                extra_packages=["./stratova_shared", "./tools"],
                env_vars=agent_env_vars,
            )
    else:
        remote_app = agent_engines.create(
            wrapped,
            display_name="KnowledgeIQ — Data Gateway (Laabu)",
            requirements=REQUIREMENTS,
            extra_packages=["./stratova_shared", "./tools"],
            env_vars=agent_env_vars,
        )
finally:
    for _tmp in (_shared_local, _tools_local):
        if _tmp.exists():
            shutil.rmtree(_tmp)
            logger.info("Cleaned up temporary bundle: %s", _tmp)

logger.info("Deployed successfully: %s", remote_app.resource_name)

try:
    set_key(str(_ENV_FILE), "AGENT_ENGINE_ID", remote_app.resource_name)
    logger.info("Updated AGENT_ENGINE_ID in .env")
except Exception as exc:
    logger.warning("Could not update .env: %s", exc)
    print(f"Resource name: {remote_app.resource_name}")

# Persist to Secret Manager
try:
    from google.cloud import secretmanager  # noqa: PLC0415
    _sm = secretmanager.SecretManagerServiceClient()
    _parent = f"projects/{GOOGLE_CLOUD_PROJECT}"
    _sid = "laabu-agents-knowledge-iq-engine-id"
    _secret_path = f"{_parent}/secrets/{_sid}"
    try:
        _sm.get_secret(request={"name": _secret_path})
    except Exception:
        _sm.create_secret(
            request={
                "parent": _parent,
                "secret_id": _sid,
                "secret": {"replication": {"automatic": {}}},
            }
        )
    _sm.add_secret_version(
        request={"parent": _secret_path, "payload": {"data": remote_app.resource_name.encode()}}
    )
    logger.info("[Secret Manager] Saved '%s'.", _sid)
except Exception as _sm_exc:
    logger.warning("[Secret Manager] Could not save engine ID (non-fatal): %s", _sm_exc)
