"""Personal Assistant agent — ADK entry point."""
from __future__ import annotations

from google.adk.agents import Agent

try:
    from .config import get_config
    from .prompts import build_instruction
except ImportError:
    from config import get_config       # Agent Engine: flat bundle
    from prompts import build_instruction

from tools.rag.personal_rag_tools import build_personal_rag_tools

root_agent = Agent(
    name="personal_assistant",
    model="gemini-2.5-flash",
    instruction=build_instruction,
    tools=build_personal_rag_tools(config_getter=get_config),
)
