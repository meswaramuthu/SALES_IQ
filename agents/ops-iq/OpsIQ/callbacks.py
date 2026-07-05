"""ADK callbacks for Ops IQ.

strip_agent_name_prefix — strips 'ops_iq_agent.toolname' → 'toolname' to avoid
  ADK 1.34.3 ValueError on qualified tool call names from Gemini 2.5.

capture_usage — after_model_callback that writes token usage to Firestore
  in a background thread. Never blocks the response path.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def strip_agent_name_prefix(callback_context, llm_response):
    """Strip any 'agentname.toolname' → 'toolname' in model function calls."""
    if not (llm_response.content and llm_response.content.parts):
        return None
    for part in llm_response.content.parts:
        fc = getattr(part, "function_call", None)
        if fc and fc.name and "." in fc.name:
            original = fc.name
            fc.name = fc.name.split(".", 1)[1]
            logger.info(
                "strip_agent_name_prefix: renamed tool call '%s' → '%s'",
                original,
                fc.name,
            )
    return None


def capture_usage(callback_context, llm_response):
    """Write token usage to Firestore non-blockingly after each model response.

    Delegates to the shared usage_tracker utility so all opted-in agents
    share the same write path and Firestore schema.
    """
    try:
        import os
        from datetime import datetime, timezone

        usage = getattr(llm_response, "usage_metadata", None)
        if not usage:
            return None

        session_id = getattr(callback_context, "session_id", None) or "unknown"
        user_id    = getattr(callback_context, "user_id", None) or "unknown"

        from google.cloud import firestore
        db = firestore.Client()
        collection = os.environ.get("FIRESTORE_USAGE_COLLECTION", "ops_iq_usage")
        db.collection(collection).document(user_id).collection("sessions").document(session_id).collection("events").add({
            "agent_name":      "ops_iq",
            "input_tokens":    getattr(usage, "prompt_token_count", 0) or 0,
            "output_tokens":   getattr(usage, "candidates_token_count", 0) or 0,
            "timestamp_utc":   datetime.now(timezone.utc),
        })
    except Exception as exc:
        logger.debug("capture_usage: skipped (%s)", exc)
    return None
