"""A2A tools — dynamically route requests to independently deployed sub-agents.

Sub-agents are declared in tools_config.json under the "sub_agents" key:

    "sub_agents": {
        "crm_agent": {
            "enabled": true,
            "resource_name": "projects/.../reasoningEngines/...",
            "agent_card_url": "gs://...",
            "description": "HubSpot CRM operations"
        },
        "my_new_agent": { ... }   ← just add an entry; no code change needed
    }

get_tools() reads this config at startup and generates one callable per
enabled sub-agent. Each callable re-reads the TTL-cached config on every
invocation so enable/disable changes take effect without a restart.

Adding a new sub-agent requires only a tools_config.json update + agent restart.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Callable

from config import get_config

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Core A2A transport — inlined so there is no dependency on stratova_shared
# ---------------------------------------------------------------------------

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
# Dynamic tool factory — one function generated per sub-agent in config
# ---------------------------------------------------------------------------

def _make_agent_tool(key: str, description: str, resource_name: str) -> Callable:
    """Generate a named, docstring-equipped tool function for one sub-agent."""

    def _tool(request: str, session_id: str) -> str:
        # Re-read TTL-cached config on every call so enable/disable is live.
        cfg = get_config()
        raw = getattr(cfg, "sub_agents", {}) or {}
        sa = raw.get(key)
        sa_dict = sa.model_dump() if hasattr(sa, "model_dump") else (sa or {})
        if not sa_dict.get("enabled", False):
            return f"[{key}] sub-agent is currently disabled."
        live_resource = sa_dict.get("resource_name", resource_name)
        return call_agent_by_resource_name(live_resource, request, session_id)

    _tool.__name__ = f"call_{key}"
    _tool.__qualname__ = f"call_{key}"
    _tool.__doc__ = (
        f"Route a request to the {description}.\n\n"
        f"Delegate any task described as '{description.lower()}' to this agent.\n"
        f"It runs independently and returns a complete natural-language response.\n\n"
        f"Args:\n"
        f"    request:    Natural-language instruction for the {key} agent.\n"
        f"    session_id: Session ID for A2A context continuity.\n"
    )
    return _tool


def get_tools() -> list[Callable]:
    """Return one tool per enabled sub-agent declared in tools_config.json.

    Called once at agent startup. New sub-agents added to the config require
    an agent restart to get a new tool function, but enable/disable changes
    take effect within CONFIG_CACHE_TTL_SECONDS without a restart.
    """
    cfg = get_config()
    raw = getattr(cfg, "sub_agents", {}) or {}
    tools: list[Callable] = []

    for key, sa in raw.items():
        sa_dict = sa.model_dump() if hasattr(sa, "model_dump") else (sa or {})
        if not sa_dict.get("enabled", False):
            logger.debug("A2A: skipping disabled sub-agent '%s'", key)
            continue
        resource_name = sa_dict.get("resource_name", "")
        description = sa_dict.get("description", key.replace("_", " ").title())
        if not resource_name:
            logger.warning("A2A: sub-agent '%s' has no resource_name — skipping", key)
            continue
        tools.append(_make_agent_tool(key, description, resource_name))
        logger.debug("A2A: registered tool 'call_%s' (%s)", key, description)

    logger.info("A2A: %d sub-agent tool(s) registered: %s",
                len(tools), [t.__name__ for t in tools])
    return tools
