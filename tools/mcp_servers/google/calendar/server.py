"""Calendar MCP — Google Calendar live slot checking and event creation.

WHY NOT GEMINI ENTERPRISE CALENDAR CONNECTOR:
The Gemini Enterprise connector creates a read-only indexed data store of
historical calendar events. It cannot answer "what slots are free RIGHT NOW?"
(requires live API) and cannot create events or send invites (write operation).
This MCP server handles both use cases directly via the Google Calendar API.
"""
from __future__ import annotations

import base64
import json
import logging
import os
_PORT = int(os.environ.get("PORT", 8080))
from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("stratova-calendar", host="0.0.0.0", port=_PORT)

_service_cache = None  # cached Calendar service — avoids re-downloading SA key every call


def _get_service():
    """Build Calendar service using DWD so the SA can invite attendees.

    Result is cached at module level — avoids re-downloading the SA key from
    GCS and re-fetching the API discovery document on every tool call.
    """
    global _service_cache
    if _service_cache is not None:
        return _service_cache

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from google.cloud import storage

    # Try GCS DWD key first (preferred — allows attendee invites)
    sa_gcs_uri = os.environ.get("GMAIL_SA_KEY_GCS_URI", "")
    calendar_user = os.environ.get("GMAIL_USER_EMAIL", "")  # impersonate calendar owner

    if sa_gcs_uri and calendar_user:
        try:
            bucket_name = sa_gcs_uri.split("/")[2]
            blob_path   = "/".join(sa_gcs_uri.split("/")[3:])
            gcs = storage.Client()
            key_json = json.loads(gcs.bucket(bucket_name).blob(blob_path).download_as_text())
            creds = Credentials.from_service_account_info(
                key_json,
                scopes=["https://www.googleapis.com/auth/calendar"],
                subject=calendar_user,  # DWD: impersonate real user → can invite attendees
            )
            _service_cache = build("calendar", "v3", credentials=creds)
            return _service_cache
        except Exception as exc:
            logger.warning("DWD key load failed (%s) — falling back to SA key", exc)

    # Fallback: plain SA key (cannot invite attendees to external emails)
    key_b64 = os.environ.get("GOOGLE_CALENDAR_SA_KEY_B64", "")
    if not key_b64:
        raise ValueError("Neither GMAIL_SA_KEY_GCS_URI nor GOOGLE_CALENDAR_SA_KEY_B64 is set")
    key_json = json.loads(base64.b64decode(key_b64))
    creds = Credentials.from_service_account_info(
        key_json, scopes=["https://www.googleapis.com/auth/calendar"]
    )
    _service_cache = build("calendar", "v3", credentials=creds)
    return _service_cache


def _find_free_slots(
    busy: list[tuple[str, str]],
    start: datetime,
    end: datetime,
    duration_minutes: int,
) -> list[str]:
    """Return up to 10 free ISO-format slot start times."""
    slots: list[str] = []
    cursor = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    # Business hours only: 9am–5pm Mon–Fri
    while cursor < end and len(slots) < 10:
        if cursor.weekday() < 5 and 9 <= cursor.hour < 17:
            slot_end = cursor + timedelta(minutes=duration_minutes)
            conflict = any(
                b_start and b_end
                and cursor < datetime.fromisoformat(b_end.replace("Z", "+00:00"))
                and slot_end > datetime.fromisoformat(b_start.replace("Z", "+00:00"))
                for b_start, b_end in busy
            )
            if not conflict:
                slots.append(cursor.isoformat())
        cursor += timedelta(minutes=30)
    return slots


@mcp.tool()
def list_upcoming_events(
    calendar_id: str = "",
    days_ahead: int = 30,
    max_results: int = 10,
) -> dict:
    """List upcoming calendar events (for reschedule / cancel flows).

    Args:
        calendar_id: Google Calendar ID. Defaults to SALESPERSON_CALENDAR_ID env var.
        days_ahead:  How many days ahead to look (default 30).
        max_results: Maximum number of events to return (default 10).
    """
    cal_id = calendar_id or os.environ.get("SALESPERSON_CALENDAR_ID") or "primary"
    try:
        service = _get_service()
        now      = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days_ahead)

        result = service.events().list(
            calendarId=cal_id,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
        ).execute()

        events = []
        for item in result.get("items", []):
            events.append({
                "event_id":  item["id"],
                "title":     item.get("summary", "(no title)"),
                "start":     item["start"].get("dateTime", item["start"].get("date", "")),
                "end":       item["end"].get("dateTime",   item["end"].get("date",   "")),
                "attendees": [a["email"] for a in item.get("attendees", [])],
                "meet_link": item.get("hangoutLink", ""),
            })

        return {"events": events, "count": len(events), "calendar_id": cal_id}
    except Exception as exc:
        logger.error("list_upcoming_events error: %s", exc)
        return {"events": [], "count": 0, "error": str(exc)}


@mcp.tool()
def cancel_calendar_event(
    event_id: str,
    calendar_id: str = "",
) -> dict:
    """Cancel (delete) a Google Calendar event and notify all attendees.

    Args:
        event_id:    The event ID from list_upcoming_events or create_calendar_event.
        calendar_id: Google Calendar ID. Defaults to SALESPERSON_CALENDAR_ID env var.
    """
    if not event_id:
        return {"status": "error", "error": "event_id is required"}
    cal_id = calendar_id or os.environ.get("SALESPERSON_CALENDAR_ID") or "primary"
    try:
        service = _get_service()
        service.events().delete(
            calendarId=cal_id,
            eventId=event_id,
            sendUpdates="all",
        ).execute()
        return {"status": "cancelled", "event_id": event_id, "calendar_id": cal_id}
    except Exception as exc:
        logger.error("cancel_calendar_event error: %s", exc)
        return {"status": "error", "error": str(exc)}


@mcp.tool()
def is_slot_available(
    start_time: str,
    duration_minutes: int = 30,
    calendar_id: str = "",
) -> dict:
    """Check whether a specific time window is free on the calendar.

    Args:
        start_time:       ISO 8601 start time e.g. "2026-06-12T15:00:00+00:00".
        duration_minutes: Duration to check in minutes (default 30).
        calendar_id:      Google Calendar ID. Defaults to SALESPERSON_CALENDAR_ID env var.
    """
    cal_id = calendar_id or os.environ.get("SALESPERSON_CALENDAR_ID") or "primary"
    try:
        service = _get_service()
        start   = datetime.fromisoformat(start_time)
        end     = start + timedelta(minutes=duration_minutes)

        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items":   [{"id": cal_id}],
        }
        fb = service.freebusy().query(body=body).execute()
        busy_periods = fb.get("calendars", {}).get(cal_id, {}).get("busy", [])

        conflicts = [
            {"start": p["start"], "end": p["end"]}
            for p in busy_periods
        ]
        return {
            "available":        len(conflicts) == 0,
            "start_time":       start.isoformat(),
            "end_time":         end.isoformat(),
            "duration_minutes": duration_minutes,
            "conflicts":        conflicts,
        }
    except Exception as exc:
        logger.error("is_slot_available error: %s", exc)
        return {"available": False, "error": str(exc)}


@mcp.tool()
def check_calendar_slots(
    calendar_id: str = "",
    duration_minutes: int = 30,
    days_ahead: int = 7,
) -> dict:
    """Find available meeting slots in a Google Calendar (live, real-time).

    Args:
        calendar_id:      Google Calendar ID. Defaults to SALESPERSON_CALENDAR_ID env var.
        duration_minutes: Meeting duration in minutes (default 30).
        days_ahead:       How many days ahead to search (default 7).
    """
    cal_id = calendar_id or os.environ.get("SALESPERSON_CALENDAR_ID") or "primary"
    try:
        service  = _get_service()
        now      = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days_ahead)

        events_result = service.events().list(
            calendarId=cal_id,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        busy = [
            (e["start"].get("dateTime"), e["end"].get("dateTime"))
            for e in events_result.get("items", [])
        ]
        slots = _find_free_slots(busy, now, time_max, duration_minutes)
        return {
            "available_slots": slots,
            "count": len(slots),
            "calendar_id": cal_id,
            "duration_minutes": duration_minutes,
        }
    except Exception as exc:
        logger.error("check_calendar_slots error: %s", exc)
        return {"available_slots": [], "count": 0, "error": str(exc)}


@mcp.tool()
def create_calendar_event(
    title: str,
    start_time: str,
    duration_minutes: int,
    attendee_emails: list,
    description: str = "",
    calendar_id: str = "",
) -> dict:
    """Create a Google Calendar event and send invites to all attendees.

    Args:
        title:            Event title e.g. "Laabu Enterprise Demo — Vantage Clinical".
        start_time:       ISO 8601 start time e.g. "2026-06-12T15:00:00+00:00".
        duration_minutes: Duration in minutes.
        attendee_emails:  List of email addresses to invite (visitor + salesperson).
        description:      Optional event description / agenda.
        calendar_id:      Calendar to create event in. Defaults to SALESPERSON_CALENDAR_ID.
    """
    cal_id = calendar_id or os.environ.get("SALESPERSON_CALENDAR_ID") or "primary"
    try:
        from googleapiclient.errors import HttpError

        service = _get_service()
        start   = datetime.fromisoformat(start_time)
        end     = start + timedelta(minutes=duration_minutes)

        # Normalise attendee_emails — LLM may pass a string, list-of-dicts, or list-of-strings
        def _extract_emails(raw) -> list[str]:
            if isinstance(raw, str):
                # "a@b.com, c@d.com" or '["a@b.com"]'
                try:
                    parsed = json.loads(raw)
                    return _extract_emails(parsed)
                except Exception:
                    return [e.strip() for e in raw.split(",") if "@" in e]
            if isinstance(raw, list):
                emails = []
                for item in raw:
                    if isinstance(item, dict):
                        emails.append(item.get("email", item.get("value", "")))
                    elif isinstance(item, str) and "@" in item:
                        emails.append(item.strip())
                return [e for e in emails if e]
            return []

        clean_emails = _extract_emails(attendee_emails)
        if not clean_emails:
            return {"status": "error", "error": "No valid attendee emails found"}

        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end":   {"dateTime": end.isoformat(),   "timeZone": "UTC"},
            "attendees": [{"email": e} for e in clean_emails],
            "conferenceData": {
                "createRequest": {"requestId": f"meet-{int(start.timestamp())}"}
            },
        }
        created = service.events().insert(
            calendarId=cal_id,
            body=event,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()

        return {
            "status": "created",
            "event_id": created["id"],
            "meet_link": created.get("hangoutLink", ""),
            "invite_sent_to": clean_emails,
            "start_time": start_time,
            "duration_minutes": duration_minutes,
        }
    except Exception as exc:
        logger.error("create_calendar_event error: %s", exc)
        return {"status": "error", "error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
