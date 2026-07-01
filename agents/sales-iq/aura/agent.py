"""AURA Sales IQ — Orchestrator agent entry point.

The orchestrator is constructed once at module load time. Dynamic behaviour comes from:
  - instruction=build_instruction  : callable, fetches prompt from GCS on every invocation
  - sub_agents                     : specialist sales sub-agents registered at start-up
  - tools from registry            : all tools registered; each re-checks the TTL-cached
                                     config on every call to honour enable/disable changes

AURA routes incoming sales requests to the appropriate sub-agent:
  discovery_agent     → lead research & ICP scoring
  qualification_agent → BANT/MEDDIC qualification
  booking_agent       → calendar scheduling & meeting management
  proposal_agent      → proposal / deck generation
  followup_agent      → automated follow-up sequencing
  revenue_agent       → pipeline analytics & forecasting
  dealdesk_agent      → deal structuring & approvals
"""
from __future__ import annotations

import os

import google.auth
from dotenv import load_dotenv
from google.adk.agents import Agent

from prompts import build_instruction
from tools.registry import get_all_tools

load_dotenv()

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

root_agent = Agent(
    model="gemini-2.5-flash",
    name="aura_sales_iq_orchestrator",
    instruction=build_instruction,
    tools=get_all_tools(),
)

app = root_agent
