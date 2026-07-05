"""Deploy the Personal Assistant agent to Vertex AI Agent Engine (always creates a fresh instance).

Run from inside the enterpriseGPT uv environment so all deps are available:
    cd agents/knowledge-iq/enterpriseGPT
    uv run python ../personal_assistant/deploy/deploy.py
"""
from __future__ import annotations

import importlib.util as _util
import json
import logging
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

import cloudpickle as _cloudpickle
import vertexai
from dotenv import load_dotenv, set_key
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent.resolve()          # deploy/
_AGENT_DIR  = _SCRIPT_DIR.parent.resolve()             # personal_assistant/
_KIQ_DIR    = _AGENT_DIR.parent.resolve()              # knowledge-iq/
_REPO_ROOT  = _KIQ_DIR.parent.parent.resolve()         # laabu-ai-app/
_ENV_FILE   = _AGENT_DIR / ".env"

load_dotenv(_ENV_FILE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT  = os.getenv("GOOGLE_CLOUD_PROJECT", "ninth-archway-496404-s2")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET   = os.getenv("STAGING_BUCKET", "gs://stratova-platform")

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

# GCS config URI for the deployed agent runtime
_TOOLS_CONFIG_GCS_URI = "gs://stratova-platform/agents/knowledge-iq/personal-copilot/tools_config.json"

# ── Purge any stale same-named modules from sys.modules ──────────────────────
# Prevents cloudpickle from bundling another agent's code if multiple deploy
# scripts run in the same Python process.
for _stale in list(sys.modules.keys()):
    if _stale in ("agent", "config", "prompts") or _stale.startswith(("agent.", "config.", "prompts.")):
        del sys.modules[_stale]
        log.debug("Evicted stale sys.modules entry: %s", _stale)

# ── Load agent modules from explicit file paths ───────────────────────────────
def _load_module_from_file(mod_name: str, file_path: Path):
    spec = _util.spec_from_file_location(mod_name, str(file_path))
    mod  = _util.module_from_spec(spec)
    sys.modules[mod_name] = mod   # register before exec so relative imports resolve
    spec.loader.exec_module(mod)
    return mod

# tools/ must be on sys.path before agent modules are loaded
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET)

log.info("Loading personal_assistant modules from explicit file paths …")
_config_mod  = _load_module_from_file("config",  _AGENT_DIR / "config.py")
_prompts_mod = _load_module_from_file("prompts", _AGENT_DIR / "prompts.py")
_agent_mod   = _load_module_from_file("agent",   _AGENT_DIR / "agent.py")

root_agent = _agent_mod.root_agent
log.info("root_agent loaded: name=%s tools=%s",
         root_agent.name, [getattr(t, "__name__", t) for t in root_agent.tools])

# Register modules by value so cloudpickle embeds their source code
for _mod_name, _mod in [("agent", _agent_mod), ("config", _config_mod), ("prompts", _prompts_mod)]:
    try:
        _cloudpickle.register_pickle_by_value(_mod)
        log.info("Registered '%s' for by-value pickling.", _mod_name)
    except Exception as _e:
        log.warning("Could not register '%s' by value: %s", _mod_name, _e)

wrapped = AdkApp(agent=root_agent, enable_tracing=True)

# ── Env vars injected into the deployed agent container ───────────────────────
# All config values (corpus, registries, DM resource name) are hardcoded in the
# GCS tools_config.json — only the pointer is needed here.
agent_env_vars: dict[str, str] = {
    "GOOGLE_GENAI_USE_VERTEXAI": "1",
    "TOOLS_CONFIG_GCS_URI": _TOOLS_CONFIG_GCS_URI,
}

log.info("Deploying personal_assistant → %s / %s", PROJECT, LOCATION)
log.info("Env vars: %s", list(agent_env_vars.keys()))
log.info("This typically takes 3–6 minutes …")

# ── Bundle agent files + tools/ into a temp dir, then deploy ─────────────────
with tempfile.TemporaryDirectory(prefix="pa_bundle_") as _tmp:
    bundle = Path(_tmp)
    for fname in ["agent.py", "config.py", "prompts.py"]:
        src = _AGENT_DIR / fname
        if src.exists():
            shutil.copy2(src, bundle / fname)
            log.info("Bundled: %s", fname)
    shutil.copytree(str(_REPO_ROOT / "tools"), str(bundle / "tools"))
    log.info("Bundled: tools/")

    os.chdir(bundle)
    remote_app = agent_engines.create(
        wrapped,
        display_name="Laabu Personal Copilot",
        requirements=REQUIREMENTS,
        extra_packages=["."],
        env_vars=agent_env_vars,
    )

resource_name: str = remote_app.resource_name
log.info("Deployed successfully: %s", resource_name)

# ── Persist resource name ─────────────────────────────────────────────────────
try:
    set_key(str(_ENV_FILE), "AGENT_ENGINE_ID", resource_name)
    log.info("Updated .env: AGENT_ENGINE_ID")
except Exception as exc:
    log.warning("Could not update .env: %s", exc)

# Save to Secret Manager (best-effort)
try:
    from google.cloud import secretmanager  # noqa: PLC0415
    _sm = secretmanager.SecretManagerServiceClient()
    _parent = f"projects/{PROJECT}"
    _sid = "laabu-agents-knowledge-iq-pa-engine-id"
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
        request={"parent": _secret_path, "payload": {"data": resource_name.encode()}}
    )
    log.info("[Secret Manager] Saved '%s'.", _sid)
except Exception as _sm_exc:
    log.warning("[Secret Manager] Could not save engine ID (non-fatal): %s", _sm_exc)

# ── Update Gemini Enterprise (Agentspace) entry ───────────────────────────────
log.info("Updating Gemini Enterprise Agentspace entry …")
try:
    import google.auth
    import google.auth.transport.requests

    _creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    _creds.refresh(google.auth.transport.requests.Request())
    _headers = {
        "Authorization": f"Bearer {_creds.token}",
        "x-goog-user-project": "ninth-archway-496404-s2",
        "Content-Type": "application/json",
    }
    _agents_url = (
        "https://discoveryengine.googleapis.com/v1alpha/projects/528271267622"
        "/locations/global/collections/default_collection"
        "/engines/stratova-gemini_1779267526762/assistants/default_assistant/agents"
    )

    # List existing entries and delete any old PA entries
    _req = urllib.request.Request(_agents_url, headers=_headers)
    with urllib.request.urlopen(_req, timeout=15) as _r:
        _existing_agents = json.loads(_r.read()).get("agents", [])

    _OLD_PA_IDS = {"6697783382492839936"}
    for _a in _existing_agents:
        _rn = (_a.get("adkAgentDefinition", {})
                  .get("provisionedReasoningEngine", {})
                  .get("reasoningEngine", ""))
        if _rn.split("/")[-1] in _OLD_PA_IDS:
            _del_url = f"https://discoveryengine.googleapis.com/v1alpha/{_a['name']}"
            _del_req = urllib.request.Request(_del_url, headers=_headers, method="DELETE")
            try:
                urllib.request.urlopen(_del_req, timeout=15)
                log.info("Removed old Agentspace entry: %s (engine: %s)", _a["name"], _rn.split("/")[-1])
            except Exception as _de:
                log.warning("Could not delete old entry %s: %s", _a["name"], _de)

    # Register new entry
    _body = json.dumps({
        "displayName": "Laabu Personal Copilot",
        "description": (
            "Your private AI copilot — searches only your own uploaded documents, "
            "helps draft emails and content, and lets you upload files to your personal "
            "knowledge base that only you can access."
        ),
        "adkAgentDefinition": {
            "provisionedReasoningEngine": {"reasoningEngine": resource_name}
        },
        "state": "ENABLED",
        "sharingConfig": {"scope": "ALL_USERS"},
    }).encode()
    _post = urllib.request.Request(_agents_url, data=_body, headers=_headers, method="POST")
    with urllib.request.urlopen(_post, timeout=30) as _r:
        _result = json.loads(_r.read())
    log.info("Agentspace entry created: %s", _result.get("name"))
except Exception as _as_exc:
    log.warning("Agentspace update failed (non-fatal): %s", _as_exc)

# ── Update orchestrator GCS config with new PA resource name ─────────────────
log.info("Patching orchestrator GCS config with new PA resource name …")
try:
    from google.cloud import storage as _gcs  # noqa: PLC0415

    _gcs_client = _gcs.Client(project=PROJECT)

    def _gcs_read(uri: str) -> dict:
        _b, _p = uri.replace("gs://", "").split("/", 1)
        return json.loads(_gcs_client.bucket(_b).blob(_p).download_as_text())

    def _gcs_write(uri: str, data: dict) -> None:
        _b, _p = uri.replace("gs://", "").split("/", 1)
        _gcs_client.bucket(_b).blob(_p).upload_from_string(
            json.dumps(data, indent=2), content_type="application/json"
        )

    # Update personal-copilot's own GCS config with the new resource name (for reference)
    # Also update orchestrator if it references the PA resource
    _OLD_PA_ENGINE_IDS = {"6697783382492839936"}
    for _cfg_uri in [
        "gs://stratova-platform/agents/knowledge-iq/orchestrator-hub/tools_config.json",
    ]:
        try:
            _cfg = _gcs_read(_cfg_uri)
            _changed = False
            for _section in [_cfg.get("sub_agents", {})]:
                for _item in _section.values():
                    if not isinstance(_item, dict):
                        continue
                    if _item.get("resource_name", "").split("/")[-1] in _OLD_PA_ENGINE_IDS:
                        _item["resource_name"] = resource_name
                        _changed = True
            if _changed:
                _gcs_write(_cfg_uri, _cfg)
                log.info("Updated PA resource name in: %s", _cfg_uri)
            else:
                log.info("No old PA resource name found in: %s", _cfg_uri)
        except Exception as _cu:
            log.warning("Could not update %s: %s", _cfg_uri, _cu)
except Exception as _dep_exc:
    log.warning("Dependent config update failed (non-fatal): %s", _dep_exc)

print(f"\n{'='*65}")
print(f"  Personal Copilot Agent deployed!")
print(f"  Resource name: {resource_name}")
print(f"{'='*65}\n")
