"""AURA Orchestrator — Firestore Session Store.

Persists AURASession documents in Firestore under:
    Collection : FIRESTORE_COLLECTION  (default: "aura_sessions")
    Document   : {user_id}_{session_id}

Design:
  - Reads / writes full session documents as plain dicts.
  - Supports partial merge via update() so sub-agent outputs can be
    written atomically without a full read-modify-write.
  - TTL expiry handled by Firestore TTL policy (set field `expires_at`).
  - Falls back gracefully to an in-process dict store if Firestore is
    unavailable (useful for local ADK `adk web` development).

Environment variables:
    FIRESTORE_PROJECT    — GCP project (defaults to GOOGLE_CLOUD_PROJECT)
    FIRESTORE_DATABASE   — Firestore database ID (default: "(default)")
    FIRESTORE_COLLECTION — Collection name (default: "aura_sessions")
    SESSION_TTL_DAYS     — Days before a session document expires (default: 30)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "aura_sessions")
_DATABASE   = os.environ.get("FIRESTORE_DATABASE", "(default)")
_PROJECT    = os.environ.get("FIRESTORE_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
_TTL_DAYS   = int(os.environ.get("SESSION_TTL_DAYS", "30"))

# ---------------------------------------------------------------------------
# In-process fallback store (local dev / unit tests)
# ---------------------------------------------------------------------------

class _InMemoryStore:
    """Mimics the Firestore store API using a plain dict (non-persistent)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def _doc_id(self, user_id: str, session_id: str) -> str:
        return f"{user_id}_{session_id}"

    def get(self, user_id: str, session_id: str) -> Optional[dict[str, Any]]:
        return self._store.get(self._doc_id(user_id, session_id))

    def set(self, user_id: str, session_id: str, data: dict[str, Any]) -> None:
        self._store[self._doc_id(user_id, session_id)] = data

    def update(self, user_id: str, session_id: str, partial: dict[str, Any]) -> None:
        doc_id = self._doc_id(user_id, session_id)
        existing = self._store.get(doc_id, {})
        existing.update(partial)
        self._store[doc_id] = existing

    def delete(self, user_id: str, session_id: str) -> None:
        self._store.pop(self._doc_id(user_id, session_id), None)


# ---------------------------------------------------------------------------
# Firestore store
# ---------------------------------------------------------------------------

class FirestoreSessionStore:
    """Firestore-backed session persistence for AURA.

    Each session is stored as a single Firestore document.
    The document ID is ``{user_id}_{session_id}`` to keep queries simple.
    A ``expires_at`` timestamp field is written on every set(); Firestore TTL
    policy should be configured on this field in the console.
    """

    def __init__(self) -> None:
        self._client: Any = None          # google.cloud.firestore.Client
        self._fallback: Optional[_InMemoryStore] = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            from google.cloud import firestore

            kwargs: dict[str, Any] = {}
            if _PROJECT:
                kwargs["project"] = _PROJECT
            if _DATABASE and _DATABASE != "(default)":
                kwargs["database"] = _DATABASE

            self._client = firestore.Client(**kwargs)
            logger.info(
                "Firestore session store initialised — project=%s, database=%s, collection=%s",
                _PROJECT, _DATABASE, _COLLECTION,
            )
        except Exception as exc:
            logger.warning(
                "Firestore unavailable (%s) — falling back to in-process session store. "
                "Sessions will NOT persist across restarts.",
                exc,
            )
            self._fallback = _InMemoryStore()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _col(self):
        """Return the Firestore collection reference."""
        return self._client.collection(_COLLECTION)

    @staticmethod
    def _doc_id(user_id: str, session_id: str) -> str:
        # Sanitise: Firestore doc IDs may not contain forward slashes
        uid = user_id.replace("/", "_").replace(" ", "_")[:64]
        sid = session_id.replace("/", "_").replace(" ", "_")[:64]
        return f"{uid}_{sid}"

    def _expires_at(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=_TTL_DAYS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, user_id: str, session_id: str) -> Optional[dict[str, Any]]:
        """Return the session document as a plain dict, or None if not found."""
        if self._fallback:
            return self._fallback.get(user_id, session_id)
        try:
            doc = self._col().document(self._doc_id(user_id, session_id)).get()
            if doc.exists:
                data = doc.to_dict()
                # Remove internal Firestore fields before returning
                data.pop("expires_at", None)
                return data
            return None
        except Exception as exc:
            logger.error("Firestore get failed (%s): %s", self._doc_id(user_id, session_id), exc)
            return None

    def set(self, user_id: str, session_id: str, data: dict[str, Any]) -> None:
        """Write (overwrite) the full session document."""
        if self._fallback:
            self._fallback.set(user_id, session_id, data)
            return
        try:
            payload = {**data, "expires_at": self._expires_at()}
            self._col().document(self._doc_id(user_id, session_id)).set(payload)
            logger.debug("Session written to Firestore: %s", self._doc_id(user_id, session_id))
        except Exception as exc:
            logger.error("Firestore set failed: %s", exc)

    def update(self, user_id: str, session_id: str, partial: dict[str, Any]) -> None:
        """Merge a partial update into the existing document (does not clobber other fields)."""
        if self._fallback:
            self._fallback.update(user_id, session_id, partial)
            return
        try:
            # Firestore update() uses dot-notation for nested merges; for flat
            # partial updates we just use a regular update.
            payload = {**partial, "expires_at": self._expires_at()}
            self._col().document(self._doc_id(user_id, session_id)).update(payload)
            logger.debug("Session partial-updated: %s | keys=%s", self._doc_id(user_id, session_id), list(partial))
        except Exception as exc:
            # Document may not exist yet — fall back to set
            logger.warning("Firestore update failed (doc may not exist yet): %s — retrying with set()", exc)
            try:
                existing = self.get(user_id, session_id) or {}
                existing.update(partial)
                self.set(user_id, session_id, existing)
            except Exception as exc2:
                logger.error("Firestore fallback set also failed: %s", exc2)

    def delete(self, user_id: str, session_id: str) -> None:
        """Delete a session document."""
        if self._fallback:
            self._fallback.delete(user_id, session_id)
            return
        try:
            self._col().document(self._doc_id(user_id, session_id)).delete()
            logger.info("Session deleted: %s", self._doc_id(user_id, session_id))
        except Exception as exc:
            logger.error("Firestore delete failed: %s", exc)

    def list_sessions_for_user(self, user_id: str, limit: int = 20) -> list[str]:
        """Return a list of session IDs for a given user (for management UIs)."""
        if self._fallback:
            prefix = user_id.replace("/", "_").replace(" ", "_")[:64] + "_"
            return [k.replace(prefix, "", 1) for k in self._fallback._store if k.startswith(prefix)][:limit]
        try:
            uid = user_id.replace("/", "_").replace(" ", "_")[:64]
            docs = (
                self._col()
                .where("user_id", "==", user_id)
                .order_by("updated_at", direction="DESCENDING")
                .limit(limit)
                .stream()
            )
            return [doc.id.replace(f"{uid}_", "", 1) for doc in docs]
        except Exception as exc:
            logger.error("Firestore list_sessions_for_user failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Module-level singleton — imported by session_manager.py
# ---------------------------------------------------------------------------

_store: Optional[FirestoreSessionStore] = None


def get_store() -> FirestoreSessionStore:
    global _store
    if _store is None:
        _store = FirestoreSessionStore()
    return _store
