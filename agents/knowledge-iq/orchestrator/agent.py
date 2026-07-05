"""Knowledge-IQ Orchestrator entry point.

Routes all incoming knowledge requests to the correct specialist agent:
  - Document upload / ingest → document_mining_agent
  - Knowledge search / retrieval → knowledge_search_agent (enterpriseGPT)

Any agent in the platform (CRM, web scraper, enrichment, etc.) that needs to
store a document in the knowledge base calls this orchestrator. The orchestrator
forwards the request to the document-mining agent, which handles analysis,
scope confirmation with the user, and RAG upload with full metadata tagging.
"""
from __future__ import annotations

import os

import google.auth
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig, StreamingMode
from vertexai.preview.reasoning_engines import AdkApp

try:
    from .config import get_config       # adk web: loaded as package
    from .prompts import build_instruction
except ImportError:
    from config import get_config        # Agent Engine: flat bundle
    from prompts import build_instruction
from tools.a2a.a2a_tools import build_a2a_tools

load_dotenv()

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

root_agent = Agent(
    model="gemini-2.5-flash",
    name="knowledge_iq_orchestrator",
    instruction=build_instruction,
    tools=build_a2a_tools(config_getter=get_config),
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
