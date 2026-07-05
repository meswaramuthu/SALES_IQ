"""Personal Assistant agent — ADK entry point."""
from __future__ import annotations

from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig, StreamingMode
from vertexai.preview.reasoning_engines import AdkApp

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


class StreamingAdkApp(AdkApp):
    """AdkApp with SSE streaming to avoid blank responses on long requests."""

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
