"""Deploy knowledge-iq orchestrator to Vertex AI Agent Engine (always creates a fresh instance).

Requires the resource names of the two sub-agents that were deployed first:
    --dm-resource    : deployed document-mining Agent Engine resource name
    --egpt-resource  : deployed enterpriseGPT Agent Engine resource name

Run from anywhere inside the enterpriseGPT uv environment so all deps are available:
    cd agents/knowledge-iq/enterpriseGPT
    uv run python ../orchestrator/deploy/deploy.py \\
        --dm-resource   projects/.../reasoningEngines/DM_ID \\
        --egpt-resource projects/.../reasoningEngines/EGPT_ID
"""
from __future__ import annotations

import argparse
import importlib as _importlib
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

import cloudpickle as _cloudpickle
import vertexai
from dotenv import load_dotenv, set_key
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent.resolve()          # deploy/
_AGENT_DIR  = _SCRIPT_DIR.parent.resolve()             # orchestrator/
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


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Deploy Knowledge-IQ Orchestrator to Vertex AI Agent Engine.",
    )
    p.add_argument(
        "--dm-resource",
        default="",
        help="Document-Mining Agent Engine resource name (projects/.../reasoningEngines/ID)",
    )
    p.add_argument(
        "--egpt-resource",
        default="",
        help="EnterpriseGPT Agent Engine resource name (projects/.../reasoningEngines/ID)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    # CLI args override .env values
    dm_resource   = args.dm_resource   or os.getenv("DOCUMENT_MINING_AGENT_RESOURCE_NAME", "")
    egpt_resource = args.egpt_resource or os.getenv("KNOWLEDGE_SEARCH_AGENT_RESOURCE_NAME", "")

    if not dm_resource or not egpt_resource:
        log.error(
            "Both --dm-resource and --egpt-resource are required.\n"
            "  --dm-resource   : document-mining Agent Engine resource name\n"
            "  --egpt-resource : enterpriseGPT Agent Engine resource name"
        )
        raise SystemExit(1)

    log.info("Sub-agent resource names:")
    log.info("  document_mining_agent : %s", dm_resource)
    log.info("  knowledge_search_agent: %s", egpt_resource)

    # Inject into os.environ so orchestrator's config.py resolves env: references
    # correctly when build_a2a_tools() is called during agent import
    os.environ["DOCUMENT_MINING_AGENT_RESOURCE_NAME"]  = dm_resource
    os.environ["KNOWLEDGE_SEARCH_AGENT_RESOURCE_NAME"] = egpt_resource
    # Ensure USE_LOCAL_CONFIG is set so the local tools_config.json is loaded,
    # which contains the env: references that are resolved above
    os.environ["USE_LOCAL_CONFIG"] = "1"

    # ── sys.path so agent.py / config.py / prompts.py and tools/ resolve ─────
    sys.path.insert(0, str(_REPO_ROOT))   # for tools/ package
    sys.path.insert(0, str(_AGENT_DIR))   # for agent.py, config.py, prompts.py

    vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET)

    log.info("Importing orchestrator agent …")
    from agent import root_agent  # noqa: E402

    # Register local modules by value so cloudpickle embeds their code
    for _mod_name in ["agent", "config", "prompts"]:
        try:
            _mod = _importlib.import_module(_mod_name)
            _cloudpickle.register_pickle_by_value(_mod)
            log.info("Registered '%s' for by-value pickling.", _mod_name)
        except Exception as _e:
            log.warning("Could not register '%s' by value: %s", _mod_name, _e)

    wrapped = AdkApp(agent=root_agent, enable_tracing=True)

    # ── Env vars injected into the deployed agent container ───────────────────
    # At runtime on Agent Engine, config.py._build_from_env() reads these to
    # construct the sub-agent routing table.
    agent_env_vars: dict[str, str] = {
        "GOOGLE_GENAI_USE_VERTEXAI":              "1",
        "DOCUMENT_MINING_AGENT_RESOURCE_NAME":    dm_resource,
        "KNOWLEDGE_SEARCH_AGENT_RESOURCE_NAME":   egpt_resource,
    }

    log.info("Deploying orchestrator → %s / %s", PROJECT, LOCATION)
    log.info("Env vars: %s", list(agent_env_vars.keys()))
    log.info("This typically takes 3–6 minutes …")

    # ── Bundle agent files + tools/ into a temp dir, then deploy ─────────────
    with tempfile.TemporaryDirectory(prefix="orch_bundle_") as _tmp:
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
            display_name="Knowledge-IQ — Orchestrator (Laabu)",
            requirements=REQUIREMENTS,
            extra_packages=["."],
            env_vars=agent_env_vars,
        )

    resource_name: str = remote_app.resource_name
    log.info("Deployed successfully: %s", resource_name)

    # ── Persist resource name ─────────────────────────────────────────────────
    try:
        set_key(str(_ENV_FILE), "AGENT_ENGINE_ID", resource_name)
        log.info("Updated .env: AGENT_ENGINE_ID")
    except Exception as exc:
        log.warning("Could not update .env: %s", exc)

    # Also save to Secret Manager (best-effort)
    try:
        from google.cloud import secretmanager  # noqa: PLC0415
        _sm = secretmanager.SecretManagerServiceClient()
        _parent = f"projects/{PROJECT}"
        _sid = "laabu-agents-knowledge-iq-orch-engine-id"
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

    print(f"\n{'='*65}")
    print(f"  Orchestrator deployed!")
    print(f"  Resource name: {resource_name}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
