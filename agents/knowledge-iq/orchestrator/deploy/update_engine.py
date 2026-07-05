"""Update the existing orchestrator Agent Engine in-place (preserves resource ID).

Run from the enterpriseGPT uv environment:
    cd agents/knowledge-iq/enterpriseGPT
    uv run python ../orchestrator/deploy/update_engine.py
"""
from __future__ import annotations

import importlib.util as _util
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

import cloudpickle as _cloudpickle
import vertexai
from dotenv import load_dotenv
from vertexai import agent_engines

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent.resolve()           # deploy/
_AGENT_DIR  = _SCRIPT_DIR.parent.resolve()              # orchestrator/
_REPO_ROOT  = _AGENT_DIR.parent.parent.parent.resolve() # laabu-ai-app/
_ENV_FILE   = _AGENT_DIR / ".env"

load_dotenv(_ENV_FILE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT         = os.getenv("GOOGLE_CLOUD_PROJECT", "ninth-archway-496404-s2")
LOCATION        = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET          = os.getenv("STAGING_BUCKET", "gs://stratova-platform")
EXISTING_ENGINE = os.getenv("AGENT_ENGINE_ID", "").strip("'\"")

if not EXISTING_ENGINE:
    sys.exit("AGENT_ENGINE_ID not set in .env — cannot update in-place.")

# Hardcoded actual resource IDs for sub-agents (no env: references)
_DM_RESOURCE   = "projects/528271267622/locations/us-central1/reasoningEngines/4131857494798499840"
_EGPT_RESOURCE = "projects/528271267622/locations/us-central1/reasoningEngines/3201864171746492416"

_TOOLS_CONFIG_GCS_URI   = "gs://stratova-platform/agents/knowledge-iq/orchestrator-hub/tools_config.json"
_TOOLS_CONFIG_LOCAL     = _AGENT_DIR / "config" / "tools_config.json"

REQUIREMENTS = [
    "google-cloud-aiplatform[adk,agent-engines]==1.153.1",
    "google-adk==1.34.3",
    "python-dotenv",
    "google-cloud-storage>=2.0",
    "google-auth>=2.36.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.8.1",
    "requests>=2.32.3",
]

# ── Upload tools_config.json to GCS with hardcoded resource IDs ───────────────
def _upload_config() -> None:
    log.info("Uploading orchestrator tools_config.json to GCS …")
    import re
    from google.cloud import storage

    config = {
        "prompt": {
            "source": "gcs",
            "gcs_uri": "gs://stratova-platform/agents/knowledge-iq/orchestrator-hub/prompt.txt",
        },
        "tools": {},
        "sub_agents": {
            "document_mining_agent": {
                "enabled": True,
                "resource_name": _DM_RESOURCE,
                "agent_card_url": "gs://stratova-platform/agents/knowledge-iq/document-intelligence/agent-card.json",
                "description": (
                    "Handles all document upload requests: analyses content, confirms accessibility "
                    "scope (organization, department, or personal) with the user, and ingests documents "
                    "into the knowledge base with full metadata tagging (source agent, category, type, "
                    "keywords, departments, owner)."
                ),
            },
            "knowledge_search_agent": {
                "enabled": True,
                "resource_name": _EGPT_RESOURCE,
                "agent_card_url": "gs://stratova-platform/agents/knowledge-iq/enterprise-search/agent-card.json",
                "description": (
                    "Searches and retrieves information from the organisational knowledge base across all "
                    "connected data sources (RAG corpus, SharePoint, GitHub, Confluence, Jira, Gmail, "
                    "Notion, OneDrive)."
                ),
            },
        },
    }

    m = re.match(r"gs://([^/]+)/(.+)", _TOOLS_CONFIG_GCS_URI)
    if not m:
        raise ValueError(f"Invalid GCS URI: {_TOOLS_CONFIG_GCS_URI}")
    client = storage.Client(project=PROJECT)
    client.bucket(m.group(1)).blob(m.group(2)).upload_from_string(
        json.dumps(config, indent=2), content_type="application/json"
    )
    log.info("Orchestrator tools_config.json uploaded → %s", _TOOLS_CONFIG_GCS_URI)


# ── Evict stale cached modules from a previous import ─────────────────────────
for _stale in list(sys.modules.keys()):
    if _stale in ("agent", "config", "prompts") or _stale.startswith(("agent.", "config.", "prompts.")):
        del sys.modules[_stale]

# ── Add repo root to sys.path so tools/ is importable ─────────────────────────
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET)

# ── Upload config first ────────────────────────────────────────────────────────
_upload_config()

# ── Load agent modules from explicit file paths ───────────────────────────────
def _load_module(mod_name: str, file_path: Path):
    spec = _util.spec_from_file_location(mod_name, str(file_path))
    mod  = _util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


log.info("Loading orchestrator modules …")
_config_mod  = _load_module("config",  _AGENT_DIR / "config.py")
_prompts_mod = _load_module("prompts", _AGENT_DIR / "prompts.py")
_agent_mod   = _load_module("agent",   _AGENT_DIR / "agent.py")

root_agent = _agent_mod.root_agent
log.info("root_agent loaded: %s  tools=%s",
         root_agent.name, [getattr(t, "__name__", t) for t in root_agent.tools])

for _mod_name, _mod in [("agent", _agent_mod), ("config", _config_mod), ("prompts", _prompts_mod)]:
    try:
        _cloudpickle.register_pickle_by_value(_mod)
        log.info("Registered '%s' for by-value pickling.", _mod_name)
    except Exception as _e:
        log.warning("Could not register '%s' by value: %s", _mod_name, _e)

StreamingAdkApp = _agent_mod.StreamingAdkApp
wrapped = StreamingAdkApp(agent=root_agent, enable_tracing=True)

agent_env_vars: dict[str, str] = {
    "GOOGLE_GENAI_USE_VERTEXAI": "1",
    "TOOLS_CONFIG_GCS_URI": _TOOLS_CONFIG_GCS_URI,
    # Explicit values as fallback — ensures env-var resolution works even if GCS load fails
    "DOCUMENT_MINING_AGENT_RESOURCE_NAME": _DM_RESOURCE,
    "KNOWLEDGE_SEARCH_AGENT_RESOURCE_NAME": _EGPT_RESOURCE,
    "KNOWLEDGE_SEARCH_AGENT_ENGINE_RESOURCE": _EGPT_RESOURCE,
    "DOCUMENT_MINING_AGENT_ENGINE_RESOURCE": _DM_RESOURCE,
}

# ── Bundle and update in-place ────────────────────────────────────────────────
with tempfile.TemporaryDirectory(prefix="orch_update_") as _tmp:
    bundle = Path(_tmp)
    for fname in ["agent.py", "config.py", "prompts.py"]:
        src = _AGENT_DIR / fname
        if src.exists():
            shutil.copy2(src, bundle / fname)
            log.info("Bundled: %s", fname)
    shutil.copytree(str(_REPO_ROOT / "tools"), str(bundle / "tools"))
    log.info("Bundled: tools/")

    os.chdir(bundle)

    log.info("Fetching existing engine: %s", EXISTING_ENGINE)
    existing_app = agent_engines.get(EXISTING_ENGINE)

    log.info("Updating engine in-place (this takes 3–6 min) …")
    updated_app = existing_app.update(
        agent_engine=wrapped,
        requirements=REQUIREMENTS,
        extra_packages=["."],
        env_vars=agent_env_vars,
    )

resource_name: str = updated_app.resource_name
log.info("Engine updated: %s", resource_name)

print(f"\n{'='*65}")
print(f"  Orchestrator Agent updated in-place!")
print(f"  Resource name: {resource_name}")
print(f"{'='*65}\n")
