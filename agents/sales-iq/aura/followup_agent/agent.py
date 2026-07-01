"""AURA Sales IQ — Follow-up Agent.

Manages automated follow-up email sequences, post-meeting nurture cadences,
re-engagement strategies, and Slack deal-room notifications.
"""
from __future__ import annotations

import os
from pydantic import BaseModel, Field

import google.auth
from google.cloud import firestore
from dotenv import load_dotenv
from google.adk.agents import Agent
from vertexai.generative_models import GenerativeModel

load_dotenv()

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id or "")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

SYSTEM_PROMPT = open(
    os.path.join(os.path.dirname(__file__), "prompt.md"), encoding="utf-8"
).read()

class FollowupResult(BaseModel):
    email_content: str = Field(description="The drafted follow-up email.")
    reminder_date: str = Field(description="The date for the next scheduled reminder (YYYY-MM-DD).")

followup_agent = Agent(
    model="gemini-2.5-flash",
    name="followup_agent",
    instruction=SYSTEM_PROMPT,
    tools=[],  # Tools injected from registry at runtime
)

def run_followup(context: str, last_interaction: str) -> FollowupResult:
    """Run the followup agent and save to Firestore."""
    prompt = (
        f"Please generate a follow-up action based on the following details:\n"
        f"## Context:\n{context}\n\n"
        f"## Last Interaction:\n{last_interaction}\n\n"
        f"Return ONLY the requested JSON structure."
    )
    
    model = GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=[SYSTEM_PROMPT]
    )
    
    response = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    
    result = FollowupResult.model_validate_json(response.text)
    
    db = firestore.Client(project=project_id)
    doc_ref = db.collection("followup_results").document()
    doc_ref.set(result.model_dump())
    
    return result

app = followup_agent

root_agent = app
