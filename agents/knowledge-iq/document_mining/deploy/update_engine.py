"""Update the existing document-mining Agent Engine in-place (preserves resource ID).

Run from the enterpriseGPT uv environment:
    cd agents/knowledge-iq/enterpriseGPT
    uv run python ../document_mining/deploy/update_engine.py
"""
from __future__ import annotations

import importlib.util as _util
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
_SCRIPT_DIR = Path(__file__).parent.resolve()          # deploy/
_AGENT_DIR  = _SCRIPT_DIR.parent.resolve()             # document_mining/
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

# ── Evict stale cached modules from a previous import ─────────────────────────
for _stale in list(sys.modules.keys()):
    if _stale in ("agent", "config", "prompts") or _stale.startswith(("agent.", "config.", "prompts.")):
        del sys.modules[_stale]

# ── Add repo root to sys.path so tools/ is importable ─────────────────────────
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET)

# ── Load agent modules from explicit file paths ───────────────────────────────
def _load_module(mod_name: str, file_path: Path):
    spec = _util.spec_from_file_location(mod_name, str(file_path))
    mod  = _util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod

log.info("Loading document-mining modules …")
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
    "TOOLS_CONFIG_GCS_URI": "gs://stratova-platform/agents/knowledge-iq/document-intelligence/tools_config.json",
}

# ── Bundle and update in-place ────────────────────────────────────────────────
with tempfile.TemporaryDirectory(prefix="dm_update_") as _tmp:
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
print(f"  Document-Mining Agent updated in-place!")
print(f"  Resource name: {resource_name}")
print(f"{'='*65}\n")
