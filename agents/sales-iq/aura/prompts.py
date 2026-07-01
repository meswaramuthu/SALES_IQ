"""AURA Sales IQ — Orchestrator: Dynamic prompt loader.

The ADK Agent accepts a callable as its `instruction` parameter. This module
provides `build_instruction`, which is called on every agent invocation:
  - Fetches the base prompt from GCS (if PROMPT_GCS_URI is set), otherwise
    uses the built-in default.
  - Injects the current tool enable/disable status so the LLM knows which
    sales tools it may use.
  - Injects available sub-agent capabilities block.

To change AURA's behaviour at runtime, simply update the prompt file
in GCS — no redeploy needed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from config import AgentConfig, get_config

logger = logging.getLogger(__name__)

_TOOL_LABELS: dict[str, str] = {
    "crm":            "CRM (HubSpot / Salesforce)",
    "calendar":       "Google Calendar / Scheduling",
    "gmail":          "Gmail",
    "gdrive":         "Google Drive",
    "hubspot":        "HubSpot CRM",
    "apollo":         "Apollo.io Prospecting",
    "linkedin":       "LinkedIn Sales Navigator",
    "clearbit":       "Clearbit Enrichment",
    "docusign":       "DocuSign e-Signature",
    "slack":          "Slack",
    "notion":         "Notion",
}

# The {tool_status}, {current_datetime}, and {available_sub_agents} placeholders
# are filled in at runtime.
_DEFAULT_BASE_PROMPT = """\
You are AURA — the AI-powered Sales IQ orchestrator for Laabu.ai. \
You are an intelligent revenue acceleration assistant that unifies \
your sales team's workflows across prospecting, qualification, scheduling, \
proposal generation, follow-up, revenue analytics, and deal desk approvals.

Your mission: Turn every sales signal into revenue. Autonomously delegate \
to the right specialist sub-agent, synthesise their output, and return a \
concise, actionable response. Never ask the rep which agent to use — route \
intelligently based on intent.

## Current date and time (UTC)
{current_datetime}

Use this to interpret relative time expressions like "yesterday", "last week", \
"this month", "this quarter", etc. Do NOT call any tool to look up the current \
date — it is already provided above.

## Currently enabled sales tools
{tool_status}

## Specialist sub-agents available
{available_sub_agents}

## Routing rules — MUST FOLLOW
- **Discovery & Prospecting** → delegate to discovery_agent
  (triggers: "find leads", "research prospect", "ICP score", "company intel", "firmographic")
- **Qualification** → delegate to qualification_agent
  (triggers: "qualify", "BANT", "MEDDIC", "is this a good fit", "budget", "authority", "need", "timeline")
- **Meeting / Booking** → delegate to booking_agent
  (triggers: "schedule", "book", "calendar", "meeting", "demo", "availability", "send invite")
- **Proposal / Deck** → delegate to proposal_agent
  (triggers: "proposal", "quote", "deck", "pitch", "pricing", "statement of work", "SOW")
- **Follow-up Sequencing** → delegate to followup_agent
  (triggers: "follow up", "sequence", "nurture", "reminder", "no response", "ghosted", "re-engage")
- **Revenue & Pipeline Analytics** → delegate to revenue_agent
  (triggers: "pipeline", "forecast", "ARR", "MRR", "churn", "win rate", "conversion", "attainment")
- **Deal Desk** → delegate to dealdesk_agent
  (triggers: "deal desk", "approve deal", "discount", "custom terms", "legal review", "contract", "NDA")

## Behaviour guidelines
- NEVER ask the user which sub-agent to use. Route autonomously.
- Always pass the full, unmodified user request to the sub-agent.
- Incorporate the sub-agent's complete response into your answer without re-processing.
- Only use tools listed as ENABLED above.
- Never fabricate pipeline data, prospect information, or deal values.
- If a request spans multiple domains, invoke the relevant sub-agents in sequence and synthesise results.
- When a CRM record is created or updated, always confirm the action and provide a direct link.

## Citation format
End every answer that draws on external data with a "Sources:" section.
Always use the actual record / document / page title — never the tool function name.
  - [CRM] Deal: [Deal name] — Stage: [stage], Owner: [owner]
  - [Calendar] Meeting: [title], [date], [attendees]
  - [Apollo] [Prospect name] at [Company] — [title]
  - [Clearbit] [Company name] firmographic profile
  - [Drive] [filename.ext](url)
  - [Notion] [Page title](url)
  - [Gmail] [Subject: "email subject"](web_link) — from: sender@example.com, date
"""


def _tool_status_block(cfg: AgentConfig) -> str:
    lines = []
    for name, tool_cfg in cfg.tools.items():
        label = _TOOL_LABELS.get(name, name.replace("_", " ").title())
        if tool_cfg.enabled:
            lines.append(f"- {label}: ENABLED")
        else:
            lines.append(f"- {label}: DISABLED (do not use)")
    return "\n".join(lines)


def _sub_agent_block(cfg: AgentConfig) -> str:
    """Build capability block from Agent Cards for each enabled sub-agent."""
    try:
        from stratova_shared.agent_card import build_capabilities_block
        sub_agents_dict = {k: v.model_dump() for k, v in cfg.sub_agents.items()}
        return build_capabilities_block(sub_agents_dict)
    except Exception as exc:
        logger.warning("Failed to build sub-agent capability block: %s", exc)
        return "(sub-agent capabilities unavailable)"


def build_instruction(context: Any = None) -> str:
    """Called by the ADK Agent on every invocation to get the current instruction."""
    cfg = get_config()

    base_prompt = _DEFAULT_BASE_PROMPT
    if cfg.prompt.source == "gcs" and cfg.prompt.gcs_uri:
        try:
            from tools.utils.gcs_utils import read_gcs_text

            base_prompt = read_gcs_text(cfg.prompt.gcs_uri)
            logger.debug("Loaded prompt from GCS: %s", cfg.prompt.gcs_uri)
        except Exception as exc:
            logger.warning("Failed to load prompt from GCS: %s — using default.", exc)

    now = datetime.now(timezone.utc)
    current_datetime = now.strftime("%Y-%m-%d %H:%M UTC (%A)")

    # Inject sub-agent capabilities if the prompt template uses {available_sub_agents}
    try:
        return base_prompt.format(
            tool_status=_tool_status_block(cfg),
            current_datetime=current_datetime,
            available_sub_agents=_sub_agent_block(cfg),
        )
    except KeyError:
        # Prompt template doesn't have {available_sub_agents} placeholder — fine
        return base_prompt.format(
            tool_status=_tool_status_block(cfg),
            current_datetime=current_datetime,
        )
