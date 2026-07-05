"""AURA Sales IQ — Deal Desk Agent.

Handles complex deal structuring, discount approval workflows, custom contract terms,
multi-year deal configurations, and DocuSign contract management.
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

class DealDeskResult(BaseModel):
    discount_valid: bool = Field(description="Whether the requested discount is valid.")
    approval_status: str = Field(description="The approval status of the deal (e.g., 'Approved', 'Rejected', 'Requires VP Approval').")
    contract_issues: list[str] = Field(description="A list of identified contract issues or non-standard terms.")

dealdesk_agent = Agent(
    model="gemini-2.5-flash",
    name="dealdesk_agent",
    instruction=SYSTEM_PROMPT,
    tools=[],  # Tools injected from registry at runtime
)

def run_dealdesk(deal_terms: str, discount_requested: float) -> DealDeskResult:
    """Run the dealdesk agent and save to Firestore."""
    prompt = (
        f"Please analyze the following deal:\n"
        f"## Deal Terms:\n{deal_terms}\n\n"
        f"## Discount Requested:\n{discount_requested}%\n\n"
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
    
    result = DealDeskResult.model_validate_json(response.text)
    
    db = firestore.Client(project=project_id)
    doc_ref = db.collection("dealdesk_results").document()
    doc_ref.set(result.model_dump())
    
    return result

app = dealdesk_agent

root_agent = app
