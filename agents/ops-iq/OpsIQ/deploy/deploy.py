"""Deploy Ops IQ to Vertex AI Agent Engine."""
import json
import logging
import os
import shutil
from pathlib import Path

import vertexai
from dotenv import load_dotenv, set_key
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GOOGLE_CLOUD_PROJECT  = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET        = os.getenv("STAGING_BUCKET")
ENV_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))

REQUIREMENTS = [
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

vertexai.init(
    project=GOOGLE_CLOUD_PROJECT,
    location=GOOGLE_CLOUD_LOCATION,
    staging_bucket=STAGING_BUCKET,
)

from agent import app as adk_app  # noqa: E402

wrapped = AdkApp(agent=adk_app, enable_tracing=True)

agent_env_vars: dict[str, str] = {"GOOGLE_GENAI_USE_VERTEXAI": "1"}

for key in ["TOOLS_CONFIG_GCS_URI", "PROMPT_GCS_URI", "FIRESTORE_USAGE_COLLECTION"]:
    val = os.getenv(key, "")
    if val:
        agent_env_vars[key] = val

_agent_root  = Path(__file__).parent.parent          # OpsIQ/
_config_path = _agent_root / "config" / "tools_config.json"
if _config_path.exists():
    _config_data = json.loads(_config_path.read_text())
    for tool_cfg in _config_data.get("tools", {}).values():
        for value in tool_cfg.get("config", {}).values():
            if isinstance(value, str) and value.startswith("env:"):
                env_key = value[4:]
                env_val = os.environ.get(env_key, "")
                if env_val:
                    agent_env_vars[env_key] = env_val
    for env_key in _config_data.get("env_vars", []):
        env_val = os.environ.get(env_key, "")
        if env_val:
            agent_env_vars[env_key] = env_val

logger.info("Env vars being forwarded: %s", list(agent_env_vars.keys()))
logger.info("Deploying Ops IQ…")

# repo root is 4 levels up from OpsIQ/deploy/
_repo_root   = Path(__file__).parents[4]
_tools_src   = _repo_root / "tools"           # laabu-ai-app/tools/
_tools_local = _agent_root / "tools"          # OpsIQ/tools/ (temp copy for bundling)

try:
    shutil.copytree(_tools_src, _tools_local, dirs_exist_ok=True)
    existing_id = os.environ.get("AGENT_ENGINE_ID", "")
    if existing_id:
        try:
            _existing = agent_engines.get(existing_id)
            remote_app = _existing.update(
                agent_engine=wrapped,
                requirements=REQUIREMENTS,
                env_vars=agent_env_vars,
                extra_packages=["./OpsIQ", "./tools"],
            )
            logger.info("Updated existing: %s", remote_app.resource_name)
        except Exception as _upd_err:
            logger.warning("Update failed (%s) — creating new", _upd_err)
            remote_app = agent_engines.create(
                wrapped,
                display_name="Ops IQ — GCP Resource Monitor",
                requirements=REQUIREMENTS,
                extra_packages=["./OpsIQ", "./tools"],
                env_vars=agent_env_vars,
            )
    else:
        remote_app = agent_engines.create(
            wrapped,
            display_name="Ops IQ — GCP Resource Monitor",
            requirements=REQUIREMENTS,
            extra_packages=["./OpsIQ", "./tools"],
            env_vars=agent_env_vars,
        )
finally:
    if _tools_local.exists():
        shutil.rmtree(_tools_local)

logger.info("Deployed: %s", remote_app.resource_name)
try:
    set_key(ENV_FILE, "AGENT_ENGINE_ID", remote_app.resource_name)
    set_key(ENV_FILE, "OPS_IQ_RESOURCE_NAME", remote_app.resource_name)
except Exception as exc:
    logger.warning("Could not update .env: %s", exc)
    print(f"Resource name: {remote_app.resource_name}")
