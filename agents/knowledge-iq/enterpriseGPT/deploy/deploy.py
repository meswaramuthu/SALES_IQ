"""Deploy Knowledge IQ to Vertex AI Agent Engine."""
import json
import logging
import os
import shutil
from pathlib import Path

import vertexai
from dotenv import load_dotenv, set_key
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp
from stratova_shared.session_service import build_resilient_session_service

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.getenv("STAGING_BUCKET")
ENV_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))

REQUIREMENTS = [
    "google-cloud-aiplatform[adk,agent_engines]>=1.148.1,<2",
    "google-adk==1.34.3",   # pin — newer ADK adds agent.mode which LlmAgent doesn't have
    "mcp==1.27.2",           # pin to match google-adk 1.34.3 tested combination
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

vertexai.init(
    project=GOOGLE_CLOUD_PROJECT,
    location=GOOGLE_CLOUD_LOCATION,
    staging_bucket=STAGING_BUCKET,
)

from knowledge_iq.agent import app as adk_app  # noqa: E402

wrapped = AdkApp(agent=adk_app, enable_tracing=True, session_service_builder=build_resilient_session_service)

# ── Collect env vars for the remote agent ─────────────────────────────────────
# GOOGLE_GENAI_USE_VERTEXAI=1 is required — without it the agent cannot start.
# TOOLS_CONFIG_GCS_URI lets the agent read tool config from GCS at runtime.
# All "env:XXX" references in tools_config.json are resolved and forwarded.
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
_config_path = Path(__file__).parent.parent / "config" / "tools_config.json"
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

_agent_root = Path(__file__).parent.parent
_shared_src = _agent_root.parent / "shared" / "stratova_shared"
_shared_local = _agent_root / "stratova_shared"

try:
    shutil.copytree(_shared_src, _shared_local, dirs_exist_ok=True)
    logger.info("Copied stratova_shared to %s for bundling", _shared_local)

    existing_id = os.environ.get("AGENT_ENGINE_ID", "")
    if existing_id:
        try:
            _existing = agent_engines.get(existing_id)
            remote_app = _existing.update(
                agent_engine=wrapped,
                requirements=REQUIREMENTS,
                extra_packages=["./knowledge_iq", "./stratova_shared"],
                env_vars=agent_env_vars,
            )
            logger.info("Updated existing: %s", remote_app.resource_name)
        except Exception as _upd_err:
            logger.warning("Update failed (%s) — creating new", _upd_err)
            remote_app = agent_engines.create(
        wrapped,
        display_name="KnowledgeIQ — Data Gateway (Laabu)",
        requirements=REQUIREMENTS,
        extra_packages=["./knowledge_iq", "./stratova_shared"],
        env_vars=agent_env_vars,
    )
    else:
        remote_app = agent_engines.create(
        wrapped,
        display_name="KnowledgeIQ — Data Gateway (Laabu)",
        requirements=REQUIREMENTS,
        extra_packages=["./knowledge_iq", "./stratova_shared"],
        env_vars=agent_env_vars,
    )
finally:
    if _shared_local.exists():
        shutil.rmtree(_shared_local)
        logger.info("Cleaned up temporary stratova_shared bundle")

logger.info("Deployed successfully: %s", remote_app.resource_name)

try:
    set_key(ENV_FILE, "AGENT_ENGINE_ID", remote_app.resource_name)
    logger.info("Updated AGENT_ENGINE_ID in .env")
except Exception as exc:
    logger.warning("Could not update .env: %s", exc)
    print(f"Resource name: {remote_app.resource_name}")
