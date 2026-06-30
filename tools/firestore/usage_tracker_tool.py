"""Per-user usage tracking tools backed by Firestore.

Reads from the ops_iq_usage Firestore collection which is populated by
the after_model_callback in stratova_shared.usage_tracker.

Schema:
  ops_iq_usage/{user_id}/sessions/{session_id}/events/{event_id}
    → agent_name, model, input_tokens, output_tokens,
      tool_calls_count, timestamp_utc (ISO string)

IAM required: roles/datastore.viewer
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

logger = logging.getLogger(__name__)

_DEFAULT_COLLECTION = "ops_iq_usage"


def get_tools() -> list[Callable]:
    from config import get_config

    def _check_enabled() -> dict | None:
        cfg = get_config()
        tc = cfg.tools.get("user_usage_tracking")
        if not tc or not tc.enabled:
            return {"status": "disabled", "message": "User usage tracking is currently disabled."}
        return None

    def _collection() -> str:
        cfg = get_config()
        tc = cfg.tools.get("user_usage_tracking")
        if tc:
            return tc.config.get("firestore_collection", _DEFAULT_COLLECTION)
        return _DEFAULT_COLLECTION

    def _firestore_client():
        from google.cloud import firestore

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        return firestore.Client(project=project)

    def _cutoff_dt(days: int) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=days)

    def get_user_usage_summary(user_id: str, days: int = 7) -> dict:
        """Return a usage summary for a specific user over the past N days.

        Aggregates all events from the user's sessions: total tokens consumed
        (input + output), total requests, agents used, and per-agent breakdown.

        Args:
            user_id: The user's email or identifier (must be exact match).
            days: Lookback window in days (1–90). Default 7.

        Returns:
            dict with total_input_tokens, total_output_tokens, request_count,
            agents_used, per_agent breakdown.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        if not user_id or not user_id.strip():
            return {"status": "error", "message": "user_id is required."}

        user_id = user_id.strip()
        days = max(1, min(days, 90))
        cutoff = _cutoff_dt(days)

        try:
            db = _firestore_client()
            col = _collection()

            user_doc = db.collection(col).document(user_id)
            sessions_ref = user_doc.collection("sessions")
            session_docs = sessions_ref.limit(200).stream()

            total_input = 0
            total_output = 0
            total_requests = 0
            per_agent: dict[str, dict] = {}

            for session_doc in session_docs:
                events_ref = session_doc.reference.collection("events")
                for event in events_ref.limit(500).stream():
                    ev = event.to_dict()
                    ts_str = ev.get("timestamp_utc", "")
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts < cutoff:
                            continue
                    except (ValueError, TypeError):
                        continue

                    inp = ev.get("input_tokens", 0) or 0
                    out = ev.get("output_tokens", 0) or 0
                    agent = ev.get("agent_name", "unknown")

                    total_input += inp
                    total_output += out
                    total_requests += 1
                    per_agent.setdefault(agent, {"agent_name": agent, "input_tokens": 0, "output_tokens": 0, "requests": 0})
                    per_agent[agent]["input_tokens"] += inp
                    per_agent[agent]["output_tokens"] += out
                    per_agent[agent]["requests"] += 1

            if total_requests == 0:
                return {
                    "status": "no_data",
                    "user_id": user_id,
                    "days": days,
                    "message": f"No usage data found for '{user_id}' in the last {days} days.",
                }

            per_agent_list = sorted(per_agent.values(), key=lambda x: x["input_tokens"] + x["output_tokens"], reverse=True)
            logger.info("get_user_usage_summary: user=%s days=%d requests=%d", user_id, days, total_requests)
            return {
                "status": "success",
                "user_id": user_id,
                "days": days,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_tokens": total_input + total_output,
                "total_requests": total_requests,
                "agents_used": list(per_agent.keys()),
                "per_agent": per_agent_list,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_user_usage_summary error user=%s: %s", user_id, err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading usage data. Ensure roles/datastore.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve user usage data. Please try again shortly."}

    def get_top_users(days: int = 7, limit: int = 10) -> dict:
        """Return a leaderboard of users ranked by total token consumption.

        Scans across all user documents in the usage collection and aggregates
        token usage for the specified period.

        Args:
            days: Lookback window in days (1–90). Default 7.
            limit: Maximum number of users to return (1–50). Default 10.

        Returns:
            dict with ranked list of users and their token totals.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        days = max(1, min(days, 90))
        limit = max(1, min(limit, 50))
        cutoff = _cutoff_dt(days)

        try:
            db = _firestore_client()
            col = _collection()

            user_docs = db.collection(col).limit(200).stream()
            user_totals: dict[str, dict] = {}

            for user_doc in user_docs:
                uid = user_doc.id
                sessions_ref = user_doc.reference.collection("sessions")
                for session_doc in sessions_ref.limit(100).stream():
                    for event in session_doc.reference.collection("events").limit(500).stream():
                        ev = event.to_dict()
                        ts_str = ev.get("timestamp_utc", "")
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if ts < cutoff:
                                continue
                        except (ValueError, TypeError):
                            continue

                        inp = ev.get("input_tokens", 0) or 0
                        out = ev.get("output_tokens", 0) or 0
                        user_totals.setdefault(uid, {"user_id": uid, "input_tokens": 0, "output_tokens": 0, "requests": 0})
                        user_totals[uid]["input_tokens"] += inp
                        user_totals[uid]["output_tokens"] += out
                        user_totals[uid]["requests"] += 1

            if not user_totals:
                return {
                    "status": "no_data",
                    "days": days,
                    "message": f"No usage data found in the last {days} days.",
                }

            ranked = sorted(user_totals.values(), key=lambda x: x["input_tokens"] + x["output_tokens"], reverse=True)
            for r in ranked:
                r["total_tokens"] = r["input_tokens"] + r["output_tokens"]

            logger.info("get_top_users: days=%d users=%d", days, len(ranked))
            return {
                "status": "success",
                "days": days,
                "total_users": len(ranked),
                "top_users": ranked[:limit],
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_top_users error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading usage data. Ensure roles/datastore.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve top users data. Please try again shortly."}

    def get_session_history(user_id: str, session_id: str = "", limit: int = 20) -> dict:
        """Return the chronological interaction history for a user or specific session.

        Lists individual LLM interactions with agent, model, token counts, and timestamp.

        Args:
            user_id: The user's identifier (required).
            session_id: Specific session ID. If empty, returns the most recent
                        interactions across all sessions.
            limit: Maximum events to return (1–100). Default 20.

        Returns:
            dict with ordered list of interaction events.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        if not user_id or not user_id.strip():
            return {"status": "error", "message": "user_id is required."}

        user_id = user_id.strip()
        limit = max(1, min(limit, 100))

        try:
            db = _firestore_client()
            col = _collection()
            user_ref = db.collection(col).document(user_id)

            events = []
            if session_id:
                session_ref = user_ref.collection("sessions").document(session_id)
                for ev_doc in session_ref.collection("events").order_by("timestamp_utc").limit(limit).stream():
                    ev = ev_doc.to_dict()
                    ev["session_id"] = session_id
                    events.append(ev)
            else:
                sessions = user_ref.collection("sessions").limit(50).stream()
                all_events = []
                for session_doc in sessions:
                    for ev_doc in session_doc.reference.collection("events").limit(limit).stream():
                        ev = ev_doc.to_dict()
                        ev["session_id"] = session_doc.id
                        all_events.append(ev)
                all_events.sort(key=lambda x: x.get("timestamp_utc", ""), reverse=True)
                events = all_events[:limit]

            if not events:
                return {
                    "status": "no_data",
                    "user_id": user_id,
                    "message": "No session history found for this user.",
                }

            logger.info("get_session_history: user=%s session=%s events=%d", user_id, session_id or "all", len(events))
            return {
                "status": "success",
                "user_id": user_id,
                "session_id": session_id or "all",
                "event_count": len(events),
                "events": events,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_session_history error user=%s: %s", user_id, err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading session history. Ensure roles/datastore.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve session history. Please try again shortly."}

    def get_agent_usage_breakdown(agent_name: str = "", days: int = 7) -> dict:
        """Return token and request statistics broken down by agent.

        Aggregates usage across all users for the specified agent (or all agents).
        Useful for understanding which agent is the highest cost driver.

        Args:
            agent_name: Specific agent to filter (e.g. "knowledge_iq"). Empty = all agents.
            days: Lookback window in days (1–90). Default 7.

        Returns:
            dict with per-agent totals and overall platform totals.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        days = max(1, min(days, 90))
        cutoff = _cutoff_dt(days)

        try:
            db = _firestore_client()
            col = _collection()

            user_docs = db.collection(col).limit(200).stream()
            per_agent: dict[str, dict] = {}

            for user_doc in user_docs:
                for session_doc in user_doc.reference.collection("sessions").limit(100).stream():
                    for ev_doc in session_doc.reference.collection("events").limit(500).stream():
                        ev = ev_doc.to_dict()
                        ev_agent = ev.get("agent_name", "unknown")
                        if agent_name and ev_agent != agent_name:
                            continue

                        ts_str = ev.get("timestamp_utc", "")
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if ts < cutoff:
                                continue
                        except (ValueError, TypeError):
                            continue

                        inp = ev.get("input_tokens", 0) or 0
                        out = ev.get("output_tokens", 0) or 0
                        per_agent.setdefault(ev_agent, {"agent_name": ev_agent, "input_tokens": 0, "output_tokens": 0, "requests": 0, "unique_users": set()})
                        per_agent[ev_agent]["input_tokens"] += inp
                        per_agent[ev_agent]["output_tokens"] += out
                        per_agent[ev_agent]["requests"] += 1
                        per_agent[ev_agent]["unique_users"].add(user_doc.id)

            if not per_agent:
                return {
                    "status": "no_data",
                    "days": days,
                    "agent_filter": agent_name or "all",
                    "message": "No usage data found for the specified parameters.",
                }

            rows = []
            for a in per_agent.values():
                rows.append({
                    "agent_name": a["agent_name"],
                    "input_tokens": a["input_tokens"],
                    "output_tokens": a["output_tokens"],
                    "total_tokens": a["input_tokens"] + a["output_tokens"],
                    "requests": a["requests"],
                    "unique_users": len(a["unique_users"]),
                })
            rows.sort(key=lambda x: x["total_tokens"], reverse=True)

            logger.info("get_agent_usage_breakdown: days=%d agents=%d", days, len(rows))
            return {
                "status": "success",
                "days": days,
                "agent_filter": agent_name or "all",
                "total_agents": len(rows),
                "platform_total_tokens": sum(r["total_tokens"] for r in rows),
                "by_agent": rows,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_agent_usage_breakdown error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading usage data. Ensure roles/datastore.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve agent usage breakdown. Please try again shortly."}

    def aggregate_daily_user_usage(date_str: str = "") -> dict:
        """Aggregate and snapshot per-user token usage for a specific calendar day (UTC).

        Scans all Firestore events that fall within the given UTC date window
        (midnight-to-midnight), sums tokens per user, and writes a daily snapshot
        document to {collection}/_daily_snapshots/{date}/users/{user_id} for
        fast historical lookups without rescanning raw events.

        Args:
            date_str: Date in YYYY-MM-DD format (UTC). Defaults to yesterday.

        Returns:
            dict with snapshot date, total_users, total_tokens, and per-user aggregates.

        IAM required: roles/datastore.user (write) in addition to viewer.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        if not date_str:
            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            date_str = yesterday.strftime("%Y-%m-%d")

        try:
            day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return {"status": "error", "message": f"Invalid date format '{date_str}'. Use YYYY-MM-DD."}

        day_end = day_start + timedelta(days=1)

        try:
            db = _firestore_client()
            col = _collection()

            user_docs = list(db.collection(col).limit(500).stream())
            user_totals: dict[str, dict] = {}

            for user_doc in user_docs:
                uid = user_doc.id
                if uid.startswith("_"):
                    continue  # skip internal snapshot meta documents
                for session_doc in user_doc.reference.collection("sessions").limit(100).stream():
                    for ev_doc in session_doc.reference.collection("events").limit(500).stream():
                        ev = ev_doc.to_dict()
                        ts_str = ev.get("timestamp_utc", "")
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if not (day_start <= ts < day_end):
                                continue
                        except (ValueError, TypeError):
                            continue

                        inp = ev.get("input_tokens", 0) or 0
                        out = ev.get("output_tokens", 0) or 0
                        user_totals.setdefault(uid, {
                            "user_id": uid, "input_tokens": 0,
                            "output_tokens": 0, "total_tokens": 0, "requests": 0,
                        })
                        user_totals[uid]["input_tokens"] += inp
                        user_totals[uid]["output_tokens"] += out
                        user_totals[uid]["total_tokens"] += inp + out
                        user_totals[uid]["requests"] += 1

            ranked = sorted(user_totals.values(), key=lambda x: x["total_tokens"], reverse=True)
            total_tokens = sum(u["total_tokens"] for u in ranked)

            # Write snapshot (best-effort — fails gracefully if write permission absent)
            try:
                snap_ref = (
                    db.collection(col)
                    .document("_daily_snapshots")
                    .collection("dates")
                    .document(date_str)
                )
                snap_ref.set({
                    "date": date_str,
                    "aggregated_at": datetime.now(timezone.utc).isoformat(),
                    "total_users": len(ranked),
                    "total_tokens": total_tokens,
                })
                users_col = snap_ref.collection("users")
                for u in ranked:
                    users_col.document(u["user_id"]).set(u)
                snapshot_written = True
            except Exception as write_exc:
                logger.warning("Snapshot write skipped (no write permission?): %s", write_exc)
                snapshot_written = False

            if not ranked:
                return {
                    "status": "no_data",
                    "date": date_str,
                    "message": f"No usage events found for {date_str}.",
                    "snapshot_written": snapshot_written,
                }

            logger.info("aggregate_daily_user_usage: date=%s users=%d tokens=%d", date_str, len(ranked), total_tokens)
            return {
                "status": "success",
                "date": date_str,
                "total_users": len(ranked),
                "total_tokens": total_tokens,
                "snapshot_written": snapshot_written,
                "users": ranked,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("aggregate_daily_user_usage error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading usage data. Ensure roles/datastore.viewer is granted."}
            return {"status": "error", "message": f"Daily aggregation failed: {err[:300]}"}

    def aggregate_daily_agent_usage(date_str: str = "") -> dict:
        """Aggregate and snapshot per-agent token usage for a specific calendar day (UTC).

        Scans all Firestore events that fall within the given UTC date window
        (midnight-to-midnight), sums tokens per agent, and writes a daily snapshot
        to {collection}/_daily_snapshots/{date}/agents/{agent_name} for fast
        historical lookups without rescanning raw events.

        Args:
            date_str: Date in YYYY-MM-DD format (UTC). Defaults to yesterday.

        Returns:
            dict with snapshot date, total_agents, total_tokens, and per-agent aggregates.

        IAM required: roles/datastore.user (write) in addition to viewer.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        if not date_str:
            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            date_str = yesterday.strftime("%Y-%m-%d")

        try:
            day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return {"status": "error", "message": f"Invalid date format '{date_str}'. Use YYYY-MM-DD."}

        day_end = day_start + timedelta(days=1)

        try:
            db = _firestore_client()
            col = _collection()

            user_docs = list(db.collection(col).limit(500).stream())
            agent_totals: dict[str, dict] = {}

            for user_doc in user_docs:
                uid = user_doc.id
                if uid.startswith("_"):
                    continue
                for session_doc in user_doc.reference.collection("sessions").limit(100).stream():
                    for ev_doc in session_doc.reference.collection("events").limit(500).stream():
                        ev = ev_doc.to_dict()
                        ts_str = ev.get("timestamp_utc", "")
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if not (day_start <= ts < day_end):
                                continue
                        except (ValueError, TypeError):
                            continue

                        inp = ev.get("input_tokens", 0) or 0
                        out = ev.get("output_tokens", 0) or 0
                        ag = ev.get("agent_name", "unknown") or "unknown"
                        agent_totals.setdefault(ag, {
                            "agent_name": ag, "input_tokens": 0,
                            "output_tokens": 0, "total_tokens": 0,
                            "requests": 0, "unique_users": set(),
                        })
                        agent_totals[ag]["input_tokens"] += inp
                        agent_totals[ag]["output_tokens"] += out
                        agent_totals[ag]["total_tokens"] += inp + out
                        agent_totals[ag]["requests"] += 1
                        agent_totals[ag]["unique_users"].add(uid)

            ranked = sorted(agent_totals.values(), key=lambda x: x["total_tokens"], reverse=True)
            total_tokens = sum(a["total_tokens"] for a in ranked)

            # Convert sets to counts before snapshot write / return
            for a in ranked:
                a["unique_users"] = len(a["unique_users"])

            try:
                snap_ref = (
                    db.collection(col)
                    .document("_daily_snapshots")
                    .collection("dates")
                    .document(date_str)
                )
                snap_ref.set({
                    "date": date_str,
                    "aggregated_at": datetime.now(timezone.utc).isoformat(),
                    "total_agents": len(ranked),
                    "total_tokens": total_tokens,
                }, merge=True)
                agents_col = snap_ref.collection("agents")
                for a in ranked:
                    agents_col.document(a["agent_name"]).set(a)
                snapshot_written = True
            except Exception as write_exc:
                logger.warning("Agent snapshot write skipped: %s", write_exc)
                snapshot_written = False

            if not ranked:
                return {
                    "status": "no_data",
                    "date": date_str,
                    "message": f"No usage events found for {date_str}.",
                    "snapshot_written": snapshot_written,
                }

            logger.info("aggregate_daily_agent_usage: date=%s agents=%d tokens=%d", date_str, len(ranked), total_tokens)
            return {
                "status": "success",
                "date": date_str,
                "total_agents": len(ranked),
                "total_tokens": total_tokens,
                "snapshot_written": snapshot_written,
                "agents": ranked,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("aggregate_daily_agent_usage error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading usage data. Ensure roles/datastore.viewer is granted."}
            return {"status": "error", "message": f"Agent daily aggregation failed: {err[:300]}"}

    return [
        get_user_usage_summary,
        get_top_users,
        get_session_history,
        get_agent_usage_breakdown,
        aggregate_daily_user_usage,
        aggregate_daily_agent_usage,
    ]
