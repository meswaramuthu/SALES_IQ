"""AURA_orch — Central Sales IQ Orchestrator Agent.

Routes incoming sales requests to the appropriate specialist sub-agent
using intent detection and ADK delegation patterns.

Maintains state across turns using Firestore-backed session storage.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import google.auth
from dotenv import load_dotenv
from google.adk.agents import Agent

from AURA_orch.session.session_manager import get_session_manager
from AURA_orch.tools.registry import get_all_tools
from AURA_orch.intent.classifier import get_classifier

load_dotenv()
logger = logging.getLogger(__name__)

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id or "")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

_BASE_PROMPT = open(
    os.path.join(os.path.dirname(__file__), "prompt.md"), encoding="utf-8"
).read()


def build_instruction(context: Any = None) -> str:
    """Dynamic prompt generation for the ADK agent.
    
    Injects current datetime and Firestore session context.
    """
    now = datetime.now(timezone.utc)
    current_datetime = now.strftime("%Y-%m-%d %H:%M UTC (%A)")
    
    session_context = ""
    # context is the tool_context dict passed by ADK. We extract user/session ID.
    if isinstance(context, dict):
        user_id, session_id = get_session_manager().extract_ids(context)
        session_context = get_session_manager().get_context_summary(user_id, session_id)
        
        # We can also classify intent here and save it to session
        # User message is normally passed via context context.get('message', '') 
        # but in ADK instruction builder context is just tool_context.
        # It's fine, the LLM will just get the session context.
        logger.debug("Building instruction for user=%s session=%s", user_id, session_id)
    else:
        logger.debug("No context dict provided to build_instruction")
        
    return _BASE_PROMPT.format(
        current_datetime=current_datetime,
        session_context=session_context,
    )


orchestrator = Agent(
    model="gemini-2.5-flash",
    name="aura_orch",
    instruction=build_instruction,
    tools=get_all_tools(),
)

app = orchestrator

root_agent = app
