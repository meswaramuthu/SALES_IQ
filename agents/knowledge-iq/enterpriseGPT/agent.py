"""Knowledge IQ agent entry point.

The agent is constructed once at module load time. Dynamic behaviour comes from:
  - instruction=build_instruction  : callable, fetches prompt from GCS on every invocation
  - tools from registry            : all tools registered; each re-checks the TTL-cached
                                     config on every call to honour enable/disable changes
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
    name="knowledge_iq_agent",
    instruction=build_instruction,
    tools=get_all_tools(),
)

app = root_agent
