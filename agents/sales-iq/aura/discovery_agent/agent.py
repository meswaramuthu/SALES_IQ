"""AURA Sales IQ — Discovery Agent.

Handles lead research, ICP scoring, prospect enrichment, and market mapping.
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

class DiscoveryResult(BaseModel):
    company: str = Field(description="The name of the target company.")
    decision_maker: str = Field(description="The name or role of the key decision-maker.")
    email: str = Field(description="A presumed or discovered email address for the decision maker.")
    industry: str = Field(description="The specific industry of the company.")
    pain_points: list[str] = Field(description="A list of potential pain points the company may be experiencing based on the industry and keywords.")
    opportunity_score: int = Field(description="A score from 1-100 indicating the strength of the opportunity.")

discovery_agent = Agent(
    model="gemini-2.5-flash",
    name="discovery_agent",
    instruction=SYSTEM_PROMPT,
    tools=[],  # Tools injected from registry at runtime
)

def run_discovery(industry: str, company_size: str, location: str, keywords: list[str]) -> DiscoveryResult:
    """Run the discovery agent and save to Firestore."""
    prompt = (
        f"Please find a prospect for the following criteria:\n"
        f"- Industry: {industry}\n"
        f"- Company Size: {company_size}\n"
        f"- Location: {location}\n"
        f"- Keywords: {', '.join(keywords)}\n"
        f"Return ONLY the requested JSON structure."
    )
    
    # Initialize the Vertex AI GenerativeModel
    model = GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=[SYSTEM_PROMPT]
    )
    
    # We will use simple JSON generation
    # With gemini-2.5-flash we can use response_schema if needed, but json mode works too.
    response = model.generate_content(
        prompt,
        generation_config={
            "response_mime_type": "application/json"
        }
    )
    
    result_text = response.text
    result = DiscoveryResult.model_validate_json(result_text)
    
    # Save to Firestore
    db = firestore.Client(project=project_id)
    doc_ref = db.collection("discovery_results").document()
    doc_ref.set(result.model_dump())
    
    return result

app = discovery_agent

root_agent = app
