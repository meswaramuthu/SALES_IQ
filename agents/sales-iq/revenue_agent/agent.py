"""AURA Sales IQ — Revenue Agent.

Provides pipeline analytics, revenue forecasting, quota attainment tracking,
deal velocity metrics, and cohort-based win/loss analysis.
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

class RevenueResult(BaseModel):
    opportunity_analysis: str = Field(description="Analysis of the current opportunities.")
    forecasted_revenue: float = Field(description="The forecasted total revenue amount.")
    identified_risks: list[str] = Field(description="A list of identified risks for the deals.")

revenue_agent = Agent(
    model="gemini-2.5-flash",
    name="revenue_agent",
    instruction=SYSTEM_PROMPT,
    tools=[],  # Tools injected from registry at runtime
)

def run_revenue_analysis(pipeline_data: str) -> RevenueResult:
    """Run the revenue agent and save to Firestore."""
    prompt = (
        f"Please analyze the following pipeline data:\n"
        f"## Pipeline Data:\n{pipeline_data}\n\n"
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
    
    result = RevenueResult.model_validate_json(response.text)
    
    db = firestore.Client(project=project_id)
    doc_ref = db.collection("revenue_results").document()
    doc_ref.set(result.model_dump())
    
    return result

app = revenue_agent

root_agent = app
