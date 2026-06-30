"""A2A tools — dynamically route requests to independently deployed sub-agents.

Sub-agents are declared in tools_config.json under the "sub_agents" key:

    "sub_agents": {
        "crm_agent": {
            "enabled": true,
            "resource_name": "projects/.../reasoningEngines/...",
            "agent_card_url": "gs://bucket/agents/crm/agent-card.json",
            "description": "HubSpot CRM operations"
        },
        "my_new_agent": { ... }   ← just add an entry; no code change needed
    }

Two resource_name formats are supported:
  - "projects/.../reasoningEngines/..."  → deployed Vertex AI Agent Engine (production)
  - "local://<app_name>"                 → local ADK web server (development)
                                           set ADK_LOCAL_BASE_URL env var if not localhost:8000

Agent card usage:
  When agent_card_url is set (GCS URI or HTTP URL), build_a2a_tools() fetches
  the card at startup and generates a rich tool docstring from the card's skills,
  capabilities, and examples. This gives the orchestrator LLM full knowledge of
  what each sub-agent can do, enabling accurate routing decisions.

  The card is fetched once per build_a2a_tools() call (i.e. on agent startup
  or config reload). If the fetch fails the tool still works but falls back to
  the plain description string.

Adding a new sub-agent requires only a tools_config.json update + agent restart.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from typing import Callable

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Local ADK web transport (development)
# ---------------------------------------------------------------------------

def call_local_adk_agent(app_name: str, request: str, session_id: str) -> str:
    """Call a local ADK web agent via its REST API.

    Used during local development when agents run under `adk web` instead of
    being deployed to Vertex AI Agent Engine.

    Set ADK_LOCAL_BASE_URL to override the default http://localhost:8000.
    """
    base_url = os.environ.get("ADK_LOCAL_BASE_URL", "http://localhost:8000").rstrip("/")
    user_id = f"a2a-{session_id}"

    try:
        # Create a session for this A2A call
        session_req = urllib.request.Request(
            f"{base_url}/apps/{app_name}/users/{user_id}/sessions",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(session_req, timeout=60) as resp:
            session = json.loads(resp.read())

        # Send the request and collect the response
        run_payload = json.dumps({
            "app_name": app_name,
            "user_id": user_id,
            "session_id": session["id"],
            "new_message": {"role": "user", "parts": [{"text": request}]},
        }).encode()
        run_req = urllib.request.Request(
            f"{base_url}/run",
            data=run_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(run_req, timeout=120) as resp:
            events = json.loads(resp.read())

        parts: list[str] = []
        for event in events:
            if event.get("content", {}).get("role") == "model":
                for part in event.get("content", {}).get("parts", []):
                    if part.get("text"):
                        parts.append(part["text"])

        result = "".join(parts)
        logger.info("Local A2A: %s responded (%d chars)", app_name, len(result))
        return result or "Agent returned no response."

    except urllib.error.URLError as exc:
        logger.error("Local A2A call to %s failed: %s", app_name, exc)
        return f"[A2A error] Could not reach local agent '{app_name}' at {base_url}: {exc}"
    except Exception as exc:
        logger.error("Local A2A call to %s failed: %s", app_name, exc)
        return f"[A2A error] {exc}"


# ---------------------------------------------------------------------------
# Core A2A transport — inlined so there is no dependency on stratova_shared
# ---------------------------------------------------------------------------

def _dispatch(resource_name: str, request: str, session_id: str) -> str:
    """Route to local ADK web or deployed Agent Engine based on resource_name prefix."""
    if resource_name.startswith("local://"):
        app_name = resource_name[len("local://"):]
        return call_local_adk_agent(app_name, request, session_id)
    return call_agent_by_resource_name(resource_name, request, session_id)


def call_agent_by_resource_name(resource_name: str, request: str, session_id: str) -> str:
    """Call a deployed Vertex AI Agent Engine directly by resource name.

    Handles cold-start retries automatically (Agent Engine scales to zero
    when idle — first call can take 20-60 s; subsequent calls are <5 s).

    Args:
        resource_name: Full Agent Engine resource name
                       (projects/{proj}/locations/{loc}/reasoningEngines/{id}).
        request:       Natural-language instruction for the target agent.
        session_id:    Caller session ID used to scope the A2A sub-session.

    Returns:
        The target agent's text response, or an error string.
    """
    # Re-initialise vertexai to the region embedded in the resource name.
    # Other tools (e.g. RAG) may have set a different region; reset here so
    # Agent Engine calls always land in the correct region.
    m = re.search(r"projects/([^/]+)/locations/([^/]+)/", resource_name)
    if m:
        import vertexai as _vx
        from google.cloud.aiplatform import initializer as _ai_init
        proj, loc = m.group(1), m.group(2)
        if getattr(_ai_init.global_config, "location", None) != loc:
            _vx.init(project=proj, location=loc)

    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            from vertexai import agent_engines

            agent = agent_engines.get(resource_name)
            user_id = f"a2a-{session_id}"
            session = agent.create_session(user_id=user_id)

            parts: list[str] = []
            for event in agent.stream_query(
                message=request,
                session_id=session["id"],
                user_id=user_id,
            ):
                if isinstance(event, dict):
                    for part in event.get("content", {}).get("parts", []):
                        if part.get("text"):
                            parts.append(part["text"])
                elif hasattr(event, "text") and event.text:
                    parts.append(event.text)

            result = "".join(parts)
            if result:
                return result

            # Empty response — agent still warming up, retry
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "A2A: empty response from %s (attempt %d/%d) — retrying after warm-up",
                    resource_name.split("/")[-1], attempt, _MAX_RETRIES,
                )
                time.sleep(3 * attempt)
            else:
                return "Agent returned no response after retries."

        except Exception as exc:
            last_error = exc
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "A2A call to %s failed (attempt %d/%d): %s — retrying",
                    resource_name.split("/")[-1], attempt, _MAX_RETRIES, exc,
                )
                time.sleep(5 * attempt)
            else:
                logger.error(
                    "A2A call to %s failed after %d attempts: %s",
                    resource_name.split("/")[-1], _MAX_RETRIES, exc,
                )

    return f"[A2A error] {last_error}"


# ---------------------------------------------------------------------------
# Agent card fetching — used to build rich tool docstrings
# ---------------------------------------------------------------------------

def _fetch_agent_card(agent_card_url: str) -> dict | None:
    """Fetch and parse an agent card from a GCS URI or HTTP URL.

    Returns the parsed JSON dict, or None if the fetch fails or URL is empty.
    Failures are non-fatal — the tool still works, just with a plain description.
    """
    if not agent_card_url:
        return None
    try:
        if agent_card_url.startswith("gs://"):
            from tools.utils.gcs_utils import read_gcs_text
            return json.loads(read_gcs_text(agent_card_url))
        if agent_card_url.startswith("http"):
            req = urllib.request.Request(
                agent_card_url,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
    except Exception as exc:
        logger.debug("A2A: could not fetch agent card from '%s': %s", agent_card_url, exc)
    return None


def _build_docstring_from_card(card: dict, key: str, description: str) -> str:
    """Build a rich tool docstring from an agent card JSON.

    The docstring is what the orchestrator LLM reads to decide whether to call
    this tool. A rich, structured description with skills + examples significantly
    improves routing accuracy.
    """
    display_name = card.get("display_name") or card.get("name") or key.replace("_", " ").title()
    card_desc = card.get("description") or description

    lines = [
        f"Route a request to {display_name}.",
        "",
        card_desc,
        "",
    ]

    skills: list[dict] = card.get("skills", [])
    if skills:
        lines.append("## Capabilities")
        for skill in skills:
            name = skill.get("name") or skill.get("id") or ""
            desc = skill.get("description") or ""
            lines.append(f"- **{name}**: {desc}")
            examples = skill.get("examples") or []
            if examples:
                ex_str = " | ".join(str(e) for e in examples[:3])
                lines.append(f"  e.g. {ex_str}")
        lines.append("")

    caps: dict = card.get("capabilities", {})
    if caps:
        cap_items = []
        for k, v in caps.items():
            if isinstance(v, list):
                cap_items.append(f"{k}: {', '.join(str(i) for i in v)}")
            elif isinstance(v, bool) and v:
                cap_items.append(k)
        if cap_items:
            lines.append("## Supported features")
            for item in cap_items:
                lines.append(f"- {item}")
            lines.append("")

    lines += [
        "Args:",
        f"    request:    Natural-language instruction for the {display_name}.",
        "    session_id: Caller session ID for A2A context continuity.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dynamic tool factory — one function generated per sub-agent in config
# ---------------------------------------------------------------------------

def _make_agent_tool(
    key: str,
    description: str,
    resource_name: str,
    config_getter: Callable,
    agent_card: dict | None = None,
) -> Callable:
    """Generate a named, docstring-equipped tool function for one sub-agent.

    If agent_card is provided (fetched from agent_card_url at build time),
    the tool's docstring is generated from the card's skills and capabilities
    so the orchestrator LLM has full context for routing decisions.
    """

    def _tool(request: str, session_id: str) -> str:
        # Re-read TTL-cached config on every call so enable/disable is live.
        cfg = config_getter()
        raw = getattr(cfg, "sub_agents", {}) or {}
        sa = raw.get(key)
        sa_dict = sa.model_dump() if hasattr(sa, "model_dump") else (sa or {})
        if not sa_dict.get("enabled", False):
            return f"[{key}] sub-agent is currently disabled."
        live_resource = sa_dict.get("resource_name", resource_name)
        return _dispatch(live_resource, request, session_id)

    _tool.__name__ = f"call_{key}"
    _tool.__qualname__ = f"call_{key}"

    if agent_card:
        _tool.__doc__ = _build_docstring_from_card(agent_card, key, description)
    else:
        _tool.__doc__ = (
            f"Route a request to the {description}.\n\n"
            f"Delegate any task described as '{description.lower()}' to this agent.\n"
            f"It runs independently and returns a complete natural-language response.\n\n"
            f"Args:\n"
            f"    request:    Natural-language instruction for the {key} agent.\n"
            f"    session_id: Session ID for A2A context continuity.\n"
        )
    return _tool


def build_a2a_tools(config_getter: Callable) -> list[Callable]:
    """Return one tool per enabled sub-agent, wired to the given config_getter.

    For each sub-agent with an agent_card_url, fetches the card and uses it to
    generate a rich tool docstring so the orchestrator LLM knows each agent's
    exact skills, capabilities, and usage examples.

    Use this instead of get_tools() to avoid sys.modules caching issues when
    multiple agents with different configs run in the same process (e.g. adk web).
    """
    cfg = config_getter()
    raw = getattr(cfg, "sub_agents", {}) or {}
    tools: list[Callable] = []

    for key, sa in raw.items():
        sa_dict = sa.model_dump() if hasattr(sa, "model_dump") else (sa or {})
        if not sa_dict.get("enabled", False):
            logger.debug("A2A: skipping disabled sub-agent '%s'", key)
            continue
        resource_name = sa_dict.get("resource_name", "")
        description = sa_dict.get("description", key.replace("_", " ").title())
        agent_card_url = sa_dict.get("agent_card_url", "")

        if not resource_name:
            logger.warning("A2A: sub-agent '%s' has no resource_name — skipping", key)
            continue

        # Fetch agent card to generate a rich docstring for the LLM
        agent_card = _fetch_agent_card(agent_card_url)
        if agent_card:
            display = agent_card.get("display_name") or agent_card.get("name") or key
            logger.info("A2A: loaded card for '%s' → '%s' (%d skills)",
                        key, display, len(agent_card.get("skills", [])))
        else:
            logger.debug("A2A: no agent card for '%s' — using plain description", key)

        tools.append(_make_agent_tool(key, description, resource_name, config_getter, agent_card))
        logger.debug("A2A: registered tool 'call_%s'", key)

    logger.info("A2A: %d sub-agent tool(s) registered: %s",
                len(tools), [t.__name__ for t in tools])
    return tools


def get_tools() -> list[Callable]:
    """Backwards-compatible wrapper — imports config lazily to avoid sys.modules races."""
    from config import get_config  # noqa: PLC0415
    return build_a2a_tools(config_getter=get_config)
