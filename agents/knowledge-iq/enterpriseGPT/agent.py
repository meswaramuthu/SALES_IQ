"""Knowledge IQ agent entry point.

The agent is constructed once at module load time. Dynamic behaviour comes from:
  - instruction=build_instruction  : callable, fetches prompt from GCS on every invocation
  - tools from registry            : all tools registered; each re-checks the TTL-cached
                                     config on every call to honour enable/disable changes
"""
from __future__ import annotations

import os
import sys

# Ensure the repo root (two levels up from this file) is on sys.path so that
# the top-level `tools/` package is importable regardless of how ADK launches
# this module (PYTHONPATH from .env is set too late to affect sys.path).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from dotenv import load_dotenv

load_dotenv()

import google.auth
from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig, StreamingMode
from vertexai.preview.reasoning_engines import AdkApp

from google.genai import types as genai_types

from file_converter import convert_to_text
from prompts import build_instruction
from tools.registry import get_all_tools

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")


def _convert_office_files(callback_context, llm_request) -> None:
    """Convert unsupported Office attachments to text before sending to Gemini."""
    for content in llm_request.contents:
        if not getattr(content, "parts", None):
            continue
        new_parts = []
        for part in content.parts:
            inline = getattr(part, "inline_data", None)
            if inline is not None:
                text = convert_to_text(inline.mime_type or "", inline.data)
                if text is not None:
                    new_parts.append(genai_types.Part(text=text))
                    continue
            new_parts.append(part)
        content.parts = new_parts
    return None


root_agent = Agent(
    model="gemini-2.5-flash",
    name="knowledge_iq_agent",
    instruction=build_instruction,
    tools=get_all_tools(),
    before_model_callback=_convert_office_files,
)

app = root_agent


class StreamingAdkApp(AdkApp):
    """AdkApp that injects StreamingMode.SSE so Gemini streams tokens in real-time.

    Without this, ADK calls generate_content (blocking) and Agentspace gets a
    blank response if the full response takes longer than the connection timeout.
    With SSE mode, tokens flow back incrementally so long responses don't time out.
    """

    def stream_query(self, *, message, user_id, session_id=None, run_config=None, **kwargs):
        if run_config is None:
            run_config = RunConfig(streaming_mode=StreamingMode.SSE).model_dump(mode="json")
        yield from super().stream_query(
            message=message,
            user_id=user_id,
            session_id=session_id,
            run_config=run_config,
            **kwargs,
        )

    async def async_stream_query(self, *, message, user_id, session_id=None, run_config=None, **kwargs):
        if run_config is None:
            run_config = RunConfig(streaming_mode=StreamingMode.SSE).model_dump(mode="json")
        async for event in super().async_stream_query(
            message=message,
            user_id=user_id,
            session_id=session_id,
            run_config=run_config,
            **kwargs,
        ):
            yield event
