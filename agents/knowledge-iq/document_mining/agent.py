"""Document-Mining Agent entry point.

Responsible for uploading documents into the Knowledge-IQ RAG corpus with:
  - AI-powered document analysis (category, type, keywords, topic)
  - Interactive accessibility scope confirmation (organization vs department)
  - Full metadata tagging on every uploaded RAG file
  - Source-agent attribution (records which agent triggered the upload)

This agent is typically reached via the Knowledge-IQ Orchestrator, which routes
upload requests from other platform agents (CRM, web scraper, etc.) to here.
"""
from __future__ import annotations

import os

import google.auth
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig, StreamingMode
from vertexai.preview.reasoning_engines import AdkApp

from tools.rag.rag_ingest_tool import build_rag_ingest_tools

try:
    from .config import get_config       # adk web: loaded as package
    from .prompts import build_instruction
except ImportError:
    from config import get_config        # Agent Engine: flat bundle
    from prompts import build_instruction

load_dotenv()

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

root_agent = Agent(
    model="gemini-2.5-flash",
    name="document_mining_agent",
    instruction=build_instruction,
    tools=build_rag_ingest_tools(config_getter=get_config),
)

app = root_agent


class StreamingAdkApp(AdkApp):
    """AdkApp with SSE streaming to prevent blank responses on long requests."""

    def stream_query(self, *, message, user_id, session_id=None, run_config=None, **kwargs):
        if run_config is None:
            run_config = RunConfig(streaming_mode=StreamingMode.SSE).model_dump(mode="json")
        yield from super().stream_query(
            message=message, user_id=user_id, session_id=session_id,
            run_config=run_config, **kwargs,
        )

    async def async_stream_query(self, *, message, user_id, session_id=None, run_config=None, **kwargs):
        if run_config is None:
            run_config = RunConfig(streaming_mode=StreamingMode.SSE).model_dump(mode="json")
        async for event in super().async_stream_query(
            message=message, user_id=user_id, session_id=session_id,
            run_config=run_config, **kwargs,
        ):
            yield event
