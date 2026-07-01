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

booking_agent = Agent(
    model="gemini-2.5-flash",
    name="booking_agent",
    instruction=SYSTEM_PROMPT,
    tools=[],  # Tools injected from registry at runtime
)

def run_booking(prospect_details: str, calendar_availability: str) -> BookingResult:
    """Run the booking agent and save to Firestore."""
    prompt = (
        f"Please schedule a meeting using the provided MCP calendar context:\n"
        f"## Prospect Details:\n{prospect_details}\n\n"
        f"## Calendar Availability:\n{calendar_availability}\n\n"
        f"Return ONLY the requested JSON structure."
    )
    
    # Initialize the Vertex AI GenerativeModel
    model = GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=[SYSTEM_PROMPT]
    )
    
    # Generate JSON response
    response = model.generate_content(
        prompt,
        generation_config={
            "response_mime_type": "application/json"
        }
    )
    
    result_text = response.text
    result = BookingResult.model_validate_json(result_text)
    
    # Save to Firestore
    db = firestore.Client(project=project_id)
    doc_ref = db.collection("booking_results").document()
    doc_ref.set(result.model_dump())
    
    return result

app = booking_agent

root_agent = app
