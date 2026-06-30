"""Ops IQ agent entry point.

The agent is constructed once at module load time. Dynamic behaviour comes from:
  - instruction=build_instruction  : callable, fetches prompt from GCS on every invocation
  - tools from registry            : all tools registered; each re-checks the TTL-cached
                                     config on every call to honour enable/disable changes
"""
from __future__ import annotations

import logging
import os
import sys

import google.auth
from dotenv import load_dotenv
from google.adk.agents import Agent

from callbacks import capture_usage, strip_agent_name_prefix
from prompts import build_instruction
from tools.ops_iq_registry import get_all_tools

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

def _after_model(callback_context, llm_response):
    """Chain: strip qualified tool names, then capture usage to Firestore."""
    strip_agent_name_prefix(callback_context, llm_response)
    return capture_usage(callback_context, llm_response)


root_agent = Agent(
    model="gemini-2.5-flash",
    name="ops_iq_agent",
    instruction=build_instruction,
    tools=get_all_tools(),
    after_model_callback=_after_model,
)

app = root_agent
