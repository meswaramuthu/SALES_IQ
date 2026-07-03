"""AURA Sales IQ — Booking Agent.

Handles all meeting scheduling: availability checks, calendar event creation,
invite sending, meeting prep briefs, and post-meeting follow-up triggers.
"""
from __future__ import annotations

import os
import json
from pydantic import BaseModel, Field

import google.auth
from google.cloud import firestore
from dotenv import load_dotenv
from google.adk.agents import Agent
from vertexai.generative_models import GenerativeModel, Part

load_dotenv()

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id or "")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

SYSTEM_PROMPT = open(
    os.path.join(os.path.dirname(__file__), "prompt.md"), encoding="utf-8"
).read()

class BookingResult(BaseModel):
    meeting_details: str = Field(description="Suggested meeting details including time, agenda, and context.")
    calendar_event_id: str = Field(description="A generated or retrieved Google Calendar event ID.")

def save_meeting_schedule(company_name: str, meeting_time: str, agenda: str, event_id: str) -> str:
    """Saves the scheduled meeting details to the database."""
    db = firestore.Client(project=project_id)
    doc_ref = db.collection("AURA_internal").document("records").collection("Meeting_schedule").document()
    doc_ref.set({
        "company_name": company_name,
        "meeting_time": meeting_time,
        "agenda": agenda,
        "event_id": event_id
    })
    return f"Successfully saved meeting schedule for {company_name}."

booking_agent = Agent(
    model="gemini-2.5-flash",
    name="booking_agent",
    instruction=SYSTEM_PROMPT,
    tools=[save_meeting_schedule],
)

app = booking_agent

root_agent = app
