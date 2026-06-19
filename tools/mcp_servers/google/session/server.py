"""Session MCP — Firestore-backed visitor session state."""
from __future__ import annotations

import logging
import os
_PORT = int(os.environ.get("PORT", 8080))
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("stratova-session", host="0.0.0.0", port=_PORT)
_db = None


def _get_db():
    global _db
    if _db is None:
        from google.cloud import firestore
        project = os.environ.get("FIRESTORE_PROJECT_ID", "")
        _db = firestore.Client(project=project) if project else firestore.Client()
    return _db


@mcp.tool()
def track_page_view(session_id: str, page_name: str, page_url: str) -> dict:
    """Log a visitor page view. Builds the intent signal used by Navigation Agent.

    Args:
        session_id: Unique visitor session identifier.
        page_name:  Human-readable page name e.g. "Marketing", "Pricing", "Support".
        page_url:   Full URL of the page viewed.
    """
    try:
        _get_db().collection("laabu_sessions").document(session_id)             .collection("page_views").add({
                "page_name": page_name,
                "page_url": page_url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        return {"logged": True, "session_id": session_id, "page": page_name}
    except Exception as exc:
        logger.error("track_page_view error: %s", exc)
        return {"logged": False, "error": str(exc)}


@mcp.tool()
def get_session_intent(session_id: str) -> dict:
    """Compute visitor intent from page history.

    Intent values:
      high_intent                  — Pricing page viewed
      marketing_automation_intent  — Marketing + Support pages viewed
      support_automation_intent    — Support-only pages viewed
      general                      — Other

    Args:
        session_id: Unique visitor session identifier.
    """
    try:
        docs = list(
            _get_db().collection("laabu_sessions").document(session_id)
            .collection("page_views").stream()
        )
        page_names = [d.to_dict().get("page_name", "").lower() for d in docs]
        intent = "general"
        if any("pricing" in p for p in page_names):
            intent = "high_intent"
        elif any("marketing" in p for p in page_names) and any("support" in p for p in page_names):
            intent = "marketing_automation_intent"
        elif any("support" in p for p in page_names):
            intent = "support_automation_intent"
        return {
            "session_id": session_id,
            "pages_viewed": page_names,
            "intent": intent,
            "page_count": len(page_names),
        }
    except Exception as exc:
        logger.error("get_session_intent error: %s", exc)
        return {"intent": "general", "error": str(exc)}


@mcp.tool()
def get_session_data(session_id: str, key: str) -> dict:
    """Read a value from the Firestore session store.

    Args:
        session_id: Unique visitor session identifier.
        key:        Session data key e.g. "deal_id", "route", "email_captured".
    """
    try:
        doc = _get_db().collection("laabu_sessions").document(session_id).get()
        value = doc.to_dict().get(key) if doc.exists else None
        return {"session_id": session_id, "key": key, "value": value}
    except Exception as exc:
        logger.error("get_session_data error: %s", exc)
        return {"value": None, "error": str(exc)}


@mcp.tool()
def set_session_data(session_id: str, key: str, value: str) -> dict:
    """Write a value to the Firestore session store.

    Args:
        session_id: Unique visitor session identifier.
        key:        Session data key e.g. "deal_id", "route", "email_captured".
        value:      String value to store.
    """
    try:
        _get_db().collection("laabu_sessions").document(session_id)             .set({key: value}, merge=True)
        return {"ok": True, "session_id": session_id, "key": key}
    except Exception as exc:
        logger.error("set_session_data error: %s", exc)
        return {"ok": False, "error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
