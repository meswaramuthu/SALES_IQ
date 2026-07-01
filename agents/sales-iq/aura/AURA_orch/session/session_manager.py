"""AURA Orchestrator — Session Manager.

High-level interface between the orchestrator and the Firestore session store.
Used by the ADK agent tools and the orchestrator routing engine.

Key responsibilities:
  1. Load / create an AURASession on each turn.
  2. Save the session back to Firestore after every routing action.
  3. Provide a concise context string for prompt injection.
  4. Expose typed upsert methods for leads, meetings, proposals, opportunities.
  5. Extract ADK session metadata (user_id, session_id) from the tool call context.

ADK context extraction:
  ADK passes a `tool_context` dict to every tool. AURA tools pull
  `user_id` and `session_id` from this dict so the session manager can
  look up the correct Firestore document without the orchestrator needing
  to track them explicitly.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .firestore_store import get_store
from .models import (
    AURASession,
    LeadData,
    MeetingRecord,
    OpportunityState,
    ProposalRecord,
    QualificationStatus,
    _now_iso,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session Manager
# ---------------------------------------------------------------------------

class SessionManager:
    """Load, cache (within a single turn), and save AURA session documents."""

    def __init__(self) -> None:
        self._store = get_store()
        # Turn-level cache: (user_id, session_id) → AURASession
        self._cache: dict[tuple[str, str], AURASession] = {}

    # ------------------------------------------------------------------
    # Core load / save
    # ------------------------------------------------------------------

    def get_session(self, user_id: str, session_id: str) -> AURASession:
        """Load from cache → Firestore → new session (in that priority)."""
        key = (user_id, session_id)
        if key in self._cache:
            return self._cache[key]

        raw = self._store.get(user_id, session_id)
        if raw:
            try:
                session = AURASession.model_validate(raw)
            except Exception as exc:
                logger.warning("Session validation failed (%s) — starting fresh: %s", session_id, exc)
                session = AURASession(session_id=session_id, user_id=user_id)
        else:
            logger.info("No existing session found — creating new: %s/%s", user_id, session_id)
            session = AURASession(session_id=session_id, user_id=user_id)

        self._cache[key] = session
        return session

    def save_session(self, session: AURASession) -> None:
        """Persist the session to Firestore and update the turn-level cache."""
        session.updated_at = _now_iso()
        self._cache[(session.user_id, session.session_id)] = session
        self._store.set(session.user_id, session.session_id, session.model_dump())
        logger.debug("Session saved: %s/%s (turn #%d)", session.user_id, session.session_id, session.turn_count)

    def partial_update(self, user_id: str, session_id: str, partial: dict[str, Any]) -> None:
        """Write a partial update to Firestore without a full round-trip.

        Use this when a sub-agent returns data that should be stored but
        you don't want to re-read the full session first.
        """
        self._store.update(user_id, session_id, partial)
        # Invalidate cache entry so next get_session() re-reads
        self._cache.pop((user_id, session_id), None)
        logger.debug("Partial update applied: %s/%s | keys=%s", user_id, session_id, list(partial))

    # ------------------------------------------------------------------
    # ADK context helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_ids(tool_context: dict[str, Any]) -> tuple[str, str]:
        """Extract (user_id, session_id) from an ADK tool context dict.

        ADK injects these under different key paths depending on version;
        this helper tries all known locations.
        """
        user_id = (
            tool_context.get("user_id")
            or tool_context.get("userId")
            or tool_context.get("adk_user_id")
            or "anonymous"
        )
        session_id = (
            tool_context.get("session_id")
            or tool_context.get("sessionId")
            or tool_context.get("adk_session_id")
            or "default"
        )
        return str(user_id), str(session_id)

    # ------------------------------------------------------------------
    # Typed convenience upserts (used by sales tool functions)
    # ------------------------------------------------------------------

    def upsert_lead(
        self,
        user_id: str,
        session_id: str,
        lead: LeadData,
    ) -> None:
        session = self.get_session(user_id, session_id)
        session.upsert_lead(lead)
        session.active_lead_id = lead.lead_id
        self.save_session(session)

    def upsert_opportunity(
        self,
        user_id: str,
        session_id: str,
        opp: OpportunityState,
    ) -> None:
        session = self.get_session(user_id, session_id)
        session.upsert_opportunity(opp)
        session.active_opportunity_id = opp.opportunity_id
        self.save_session(session)

    def upsert_meeting(
        self,
        user_id: str,
        session_id: str,
        meeting: MeetingRecord,
    ) -> None:
        session = self.get_session(user_id, session_id)
        session.upsert_meeting(meeting)
        self.save_session(session)

    def upsert_proposal(
        self,
        user_id: str,
        session_id: str,
        proposal: ProposalRecord,
    ) -> None:
        session = self.get_session(user_id, session_id)
        session.upsert_proposal(proposal)
        self.save_session(session)

    def update_qualification(
        self,
        user_id: str,
        session_id: str,
        opportunity_id: str,
        qualification: QualificationStatus,
    ) -> None:
        session = self.get_session(user_id, session_id)
        opp = session.get_opportunity(opportunity_id)
        if opp is None:
            opp = OpportunityState(opportunity_id=opportunity_id)
        opp.qualification = qualification
        session.upsert_opportunity(opp)
        self.save_session(session)

    # ------------------------------------------------------------------
    # Context injection helpers
    # ------------------------------------------------------------------

    def get_context_summary(self, user_id: str, session_id: str) -> str:
        """Return a formatted context string for prompt injection."""
        session = self.get_session(user_id, session_id)
        return session.to_context_summary()

    def record_turn(
        self,
        user_id: str,
        session_id: str,
        intent: str,
        agent_routed: str,
    ) -> None:
        """Increment turn counter and record routing metadata."""
        session = self.get_session(user_id, session_id)
        session.turn_count += 1
        session.last_intent = intent
        session.last_agent_routed = agent_routed
        self.save_session(session)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
