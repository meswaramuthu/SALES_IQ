#!/usr/bin/env python3
"""Minimal update script — pushes code changes to the existing Agent Engine.

This script does ONLY two things, in order:
  1. Upload tools_config.json → GCS  (picks up user_file_registry_uri immediately)
  2. Update the existing Vertex AI Agent Engine with new Python code
     (keeps the same resource name, so Gemini Enterprise registration stays valid)

Use this instead of deploy_full.py when you only changed Python code / config
and don't need to recreate infrastructure, the RAG corpus, or Gemini Enterprise app.

Usage (from agents/knowledge-iq/enterpriseGPT/):
    uv run --env-file .env python deploy/update_agent.py

Requirements:
    - AGENT_ENGINE_ID in .env (set automatically by deploy_full.py)
    - TOOLS_CONFIG_GCS_URI in .env
    - Valid ADC: run `gcloud auth application-default login` first
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_SCRIPT_DIR   = Path(__file__).parent.resolve()      # deploy/
_PROJECT_ROOT = _SCRIPT_DIR.parent.resolve()         # enterpriseGPT/
_REPO_ROOT    = _PROJECT_ROOT.parent.parent.parent   # laabu-ai-app/
_STATE_FILE   = _SCRIPT_DIR / "deployment_state.json"
_CONFIG_FILE  = _PROJECT_ROOT / "config" / "tools_config.json"
_ENV_FILE     = _PROJECT_ROOT / ".env"

_REQUIREMENTS = [
    "google-cloud-aiplatform[adk,agent-engines]==1.153.1",  # pin: matches pyproject.toml
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


def _upload_config(tools_config_uri: str) -> dict:
    """Upload tools_config.json to GCS. Returns config data dict."""
    log.info("━━  Step 1 › Upload tools_config.json to GCS  ━━")
    import re

    from google.cloud import storage

    config_data = json.loads(_CONFIG_FILE.read_text())
    m = re.match(r"gs://([^/]+)/(.+)", tools_config_uri)
    if not m:
        raise ValueError(f"Invalid TOOLS_CONFIG_GCS_URI: {tools_config_uri}")
    client = storage.Client()
    client.bucket(m.group(1)).blob(m.group(2)).upload_from_string(
        json.dumps(config_data, indent=2), content_type="application/json"
    )
    log.info("tools_config.json uploaded → %s", tools_config_uri)
    return config_data


def _update_agent(
    resource_name: str,
    project: str,
    location: str,
    staging_bucket: str,
    tools_config_uri: str,
    prompt_uri: str,
    config_data: dict,
) -> None:
    """Update the existing Agent Engine resource in place (keeps same resource name)."""
    log.info("")
    log.info("━━  Step 2 › Update existing Agent Engine  ━━")
    log.info("Resource: %s", resource_name)

    import importlib.util as _util
    import subprocess

    import cloudpickle as _cloudpickle
    import vertexai
    from vertexai import agent_engines

    # Install deps first
    log.info("Syncing dependencies …")
    subprocess.run(["uv", "sync"], check=True, cwd=str(_PROJECT_ROOT))

    sys.path.insert(0, str(_REPO_ROOT))    # for tools/ package at repo root
    sys.path.insert(0, str(_PROJECT_ROOT)) # for agent.py, config.py, prompts.py

    # Evict stale cached modules from any prior import in this process
    for _stale in list(sys.modules.keys()):
        if _stale in ("agent", "config", "prompts") or _stale.startswith(("agent.", "config.", "prompts.")):
            del sys.modules[_stale]

    vertexai.init(project=project, location=location, staging_bucket=staging_bucket)

    def _load_module(mod_name: str, file_path):
        spec = _util.spec_from_file_location(mod_name, str(file_path))
        mod = _util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        return mod

    _config_mod  = _load_module("config",  _PROJECT_ROOT / "config.py")
    _prompts_mod = _load_module("prompts", _PROJECT_ROOT / "prompts.py")
    _agent_mod   = _load_module("agent",   _PROJECT_ROOT / "agent.py")

    root_agent = _agent_mod.root_agent
    StreamingAdkApp = _agent_mod.StreamingAdkApp

    for _mod_name, _mod in [("agent", _agent_mod), ("config", _config_mod), ("prompts", _prompts_mod)]:
        try:
            _cloudpickle.register_pickle_by_value(_mod)
            log.info("Registered '%s' for by-value pickling.", _mod_name)
        except Exception as _e:
            log.warning("Could not register '%s' by value: %s", _mod_name, _e)

    wrapped = StreamingAdkApp(agent=root_agent, enable_tracing=True)

    # Build env vars
    agent_env_vars: dict[str, str] = {"GOOGLE_GENAI_USE_VERTEXAI": "1"}
    if tools_config_uri:
        agent_env_vars["TOOLS_CONFIG_GCS_URI"] = tools_config_uri
    if prompt_uri:
        agent_env_vars["PROMPT_GCS_URI"] = prompt_uri

    registry_uri = os.environ.get("USER_FILE_REGISTRY_URI", "")
    if registry_uri:
        agent_env_vars["USER_FILE_REGISTRY_URI"] = registry_uri

    # Forward all "env:XXX" secrets from config
    for tool_cfg in config_data.get("tools", {}).values():
        for value in tool_cfg.get("config", {}).values():
            if isinstance(value, str) and value.startswith("env:"):
                env_key = value[4:]
                env_val = os.environ.get(env_key, "")
                if env_val:
                    agent_env_vars[env_key] = env_val

    log.info("Env vars being set on remote agent: %s", sorted(agent_env_vars.keys()))

    # Bundle flat files + tools/ together so remote can import both.
    import shutil
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory(prefix="laabu_bundle_") as _tmp_bundle:
        _bundle = Path(_tmp_bundle)
        for _fname in ["agent.py", "config.py", "prompts.py", "file_converter.py"]:
            _src = _PROJECT_ROOT / _fname
            if _src.exists():
                shutil.copy2(_src, _bundle / _fname)
                log.info("Bundled flat file: %s", _fname)
        shutil.copytree(str(_REPO_ROOT / "tools"), str(_bundle / "tools"))
        log.info("Bundled: tools/")

        os.chdir(_bundle)
        log.info("extra_packages: [.]  (bundle → %s)", _bundle)

        # Update in place — same resource name, Gemini Enterprise registration untouched.
        log.info("Updating Agent Engine (this takes 3–6 min) …")
        remote_app = agent_engines.get(resource_name=resource_name)
        remote_app.update(
            agent_engine=wrapped,
            requirements=_REQUIREMENTS,
            extra_packages=["."],   # bundle root: config.py + agent.py + prompts.py + tools/
            env_vars=agent_env_vars,
        )
    # Temp dir cleaned up here
    log.info("Agent Engine updated successfully: %s", resource_name)

    # Quick smoke test
    log.info("Running smoke test …")
    try:
        session = remote_app.create_session(user_id="update-smoke-test")
        for event in remote_app.stream_query(
            session_id=session["id"],
            message="What tools do you have available?",
            user_id="update-smoke-test",
        ):
            if event.get("content"):
                log.info("Smoke test passed — updated agent is responding.")
                break
    except Exception as exc:
        log.warning("Smoke test error (agent may still be warming up): %s", exc)


def main() -> None:
    load_dotenv(str(_ENV_FILE))

    # ── Resolve config from .env / deployment_state.json ──────────────────────
    resource_name = os.environ.get("AGENT_ENGINE_ID", "")
    if not resource_name and _STATE_FILE.exists():
        state = json.loads(_STATE_FILE.read_text())
        resource_name = state.get("agent_engine", "")

    tools_config_uri = os.environ.get(
        "TOOLS_CONFIG_GCS_URI",
        "gs://stratova-platform/knowledge-iq/tools_config.json",
    )
    prompt_uri = os.environ.get("PROMPT_GCS_URI", "")

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    staging_bucket = os.environ.get(
        "STAGING_BUCKET", "gs://stratova-platform"
    )

    if not resource_name:
        log.error(
            "AGENT_ENGINE_ID not found in .env or deployment_state.json. "
            "Run deploy_full.py first."
        )
        sys.exit(1)
    if not project:
        log.error("GOOGLE_CLOUD_PROJECT not set in .env")
        sys.exit(1)

    log.info("Project        : %s", project)
    log.info("Location       : %s", location)
    log.info("Staging bucket : %s", staging_bucket)
    log.info("Agent Engine   : %s", resource_name)
    log.info("Config GCS URI : %s", tools_config_uri)

    # Step 1 — Upload config
    config_data = _upload_config(tools_config_uri)

    # Step 2 — Update agent code
    _update_agent(
        resource_name=resource_name,
        project=project,
        location=location,
        staging_bucket=staging_bucket,
        tools_config_uri=tools_config_uri,
        prompt_uri=prompt_uri,
        config_data=config_data,
    )

    log.info("")
    log.info("═" * 60)
    log.info("  Update complete!")
    log.info("  Agent Engine   : %s", resource_name)
    log.info("  Config GCS URI : %s", tools_config_uri)
    log.info("  Gemini Enterprise registration unchanged.")
    log.info("═" * 60)


if __name__ == "__main__":
    main()
