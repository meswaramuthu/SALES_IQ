"""AURA Sales IQ — Qualification Agent.

Scores prospects using BANT and MEDDIC frameworks, maps decision makers,
identifies pain points, and recommends next best actions.
"""
from __future__ import annotations

import os
import json
from typing import Literal
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

class QualificationResult(BaseModel):
    budget_score: int = Field(description="BANT Budget Score (1-5)")
    authority_score: int = Field(description="BANT Authority Score (1-5)")
    need_score: int = Field(description="BANT Need Score (1-5)")
    timeline_score: int = Field(description="BANT Timeline Score (1-5)")
    status: Literal["qualified", "warm", "cold"] = Field(description="Final qualification status: qualified, warm, or cold")

qualification_agent = Agent(
    model="gemini-2.5-flash",
    name="qualification_agent",
    instruction=SYSTEM_PROMPT,
    tools=[],  # Tools injected from registry at runtime
)

def run_qualification(company_data: str, meeting_notes: str, prospect_info: str) -> QualificationResult:
    """Run the qualification agent and save to Firestore."""
    prompt = (
        f"Please qualify this prospect based on the following information:\n"
        f"## Company Data:\n{company_data}\n\n"
        f"## Meeting Notes:\n{meeting_notes}\n\n"
        f"## Prospect Information:\n{prospect_info}\n\n"
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
    result = QualificationResult.model_validate_json(result_text)
    
    # Save to Firestore
    db = firestore.Client(project=project_id)
    doc_ref = db.collection("qualification_results").document()
    doc_ref.set(result.model_dump())
    
    return result

app = qualification_agent

root_agent = app
