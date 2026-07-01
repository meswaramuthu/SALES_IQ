"""AURA Orchestrator — Tool Registry.

Returns the complete list of tool functions registered with the ADK Agent.
Mirrors the pattern in tools/registry.py used by Knowledge IQ.

Tool groups:
  1. Sales session tools  — Firestore-backed session state management
  2. A2A sub-agent tools  — Route to the 7 specialist sub-agents via Vertex AI

All tools re-read the TTL-cached config on each call so enable/disable
changes take effect within CONFIG_CACHE_TTL_SECONDS without a redeploy.
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


def get_all_tools() -> list[Callable]:
    """Return all tools for the AURA orchestrator agent."""
    tools: list[Callable] = []

    # ── 1. Sales session tools (Firestore) ────────────────────────────────────
    try:
        from AURA_orch.tools.sales_tools import SALES_TOOLS
        tools.extend(SALES_TOOLS)
        logger.info("Sales session tools registered: %d", len(SALES_TOOLS))
    except Exception as exc:
        logger.error("Failed to load sales session tools: %s", exc)

    # ── 2. A2A sub-agent tools ────────────────────────────────────────────────
    # These are generated dynamically from the sub_agents block in tools_config.json.
    # Each enabled sub-agent gets one `call_{agent_key}` function.
    try:
        from tools.a2a import a2a_tools
        a2a = a2a_tools.get_tools()
        tools.extend(a2a)
        logger.info(
            "A2A sub-agent tools registered: %d — %s",
            len(a2a),
            [t.__name__ for t in a2a],
        )
    except Exception as exc:
        logger.warning("A2A tools unavailable (sub-agents not yet deployed?): %s", exc)

    logger.info("AURA total tools registered: %d", len(tools))
    return tools
