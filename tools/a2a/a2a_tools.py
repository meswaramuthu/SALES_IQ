"""A2A tools for KnowledgeIQ — route requests to independently deployed sub-agents.

KnowledgeIQ is the data gateway. It delegates to three independently deployed
sub-agents via Vertex AI Agent Engine A2A (stream_query REST API):
  - CRM Agent      : all HubSpot reads and writes
  - Enrichment Agent: company enrichment (SharePoint DS → Apollo fallback)
  - Web Scraper Agent: scrape any URL and index into Gemini Enterprise DS + RAG

Sub-agent resource names are read from tools_config.json (GCS-backed, TTL-cached)
under the "sub_agents" key, same pattern as the supervisor's registry.
"""
from __future__ import annotations

import logging
from typing import Callable

from config import get_config
from stratova_shared.a2a import call_agent_by_resource_name

logger = logging.getLogger(__name__)


def _get_sub_agent_resource(name: str) -> str:
    """Look up a sub-agent resource name from TTL-cached config.

    cfg.sub_agents values are SubAgentConfig Pydantic objects — convert to
    dict via model_dump() before using .get(), matching the supervisor pattern.
    """
    cfg = get_config()
    raw = getattr(cfg, "sub_agents", {}) or {}
    # Convert SubAgentConfig Pydantic objects → plain dicts for uniform access
    sub_agents = {k: (v.model_dump() if hasattr(v, "model_dump") else v)
                  for k, v in raw.items()}
    sa = sub_agents.get(name, {})
    if not sa or not sa.get("enabled", False):
        return ""
    return sa.get("resource_name", "")


def call_crm_agent(request: str, session_id: str) -> str:
    """Route a CRM request to the independently deployed CRM Agent.

    Use for ALL HubSpot operations:
    - Create leads: "Create HubSpot lead for maya@acme.com, pain: marketing campaigns"
    - Advance stages: "Advance deal HS-9821 to Qualified, set route=enterprise"
    - Add notes: "Add note to deal HS-9821: visitor confirmed 450 employees"
    - Set properties: "Set deal HS-9821 property headcount=450"
    - Read deals: "Get HubSpot deal HS-9821"

    Args:
        request:    Natural language CRM instruction.
        session_id: Visitor session ID for context continuity.
    """
    resource_name = _get_sub_agent_resource("crm_agent")
    if not resource_name:
        return "[CRM Agent] not configured — add crm_agent to sub_agents in tools_config.json"
    return call_agent_by_resource_name(resource_name, request, session_id)


def call_enrichment_agent(request: str, session_id: str) -> str:
    """Route an enrichment request to the independently deployed Enrichment Agent.

    Use to get company firmographics from a work email address. The Enrichment
    Agent checks the RAG cache first (7-day TTL), then searches the Gemini
    Enterprise SharePoint DS, then falls back to Apollo on-demand.

    Always returns headcount — critical for SME (<100) vs Enterprise (>=100) routing.

    Examples:
    - "Enrich company for email maya@vantageclinical.com"
    - "Get headcount and industry for john@largecorp.com"

    Args:
        request:    Natural language enrichment instruction including the work email.
        session_id: Visitor session ID for context continuity.
    """
    resource_name = _get_sub_agent_resource("enrichment_agent")
    if not resource_name:
        return "[Enrichment Agent] not configured — add enrichment_agent to sub_agents in tools_config.json"
    return call_agent_by_resource_name(resource_name, request, session_id)


def call_web_scraper_agent(request: str, session_id: str) -> str:
    """Route a scraping request to the independently deployed Web Scraper Agent.

    Scrapes any public URL, ingests content into Gemini Enterprise Website data
    store, and writes to RAG corpus. After ingestion, content is searchable via
    search_gemini_connectors(). No domain restrictions.

    Examples:
    - "Scrape and index https://laabu.com/marketing-package"
    - "Fetch content from https://competitor.com/pricing and store it"

    Args:
        request:    Natural language scraping instruction with the target URL.
        session_id: Visitor session ID for context continuity.
    """
    resource_name = _get_sub_agent_resource("web_scraper_agent")
    if not resource_name:
        return "[Web Scraper Agent] not configured — add web_scraper_agent to sub_agents in tools_config.json"
    return call_agent_by_resource_name(resource_name, request, session_id)


def get_tools() -> list[Callable]:
    return [call_crm_agent, call_enrichment_agent, call_web_scraper_agent]
