"""AURA Sales IQ — Proposal Agent.

Generates tailored sales proposals, pricing quotes, SOWs, and pitch decks.
Creates documents in Google Drive and sends via DocuSign when ready.
"""
from __future__ import annotations

import os
import time
from pydantic import BaseModel, Field

import google.auth
from google.cloud import storage
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

class ProposalResult(BaseModel):
    proposal_markdown: str = Field(description="Full markdown document with executive summary, scope, pricing, timeline, and next steps.")
    pdf_content: str = Field(description="Content structured and formatted specifically for PDF conversion.")
    email_version: str = Field(description="Short, persuasive email copy attaching the proposal.")

proposal_agent = Agent(
    model="gemini-2.5-flash",
    name="proposal_agent",
    instruction=SYSTEM_PROMPT,
    tools=[],  # Tools injected from registry at runtime
)

def run_proposal(company: str, requirements: str, pricing: str, services: str) -> ProposalResult:
    """Run the proposal agent and save to Cloud Storage."""
    prompt = (
        f"Please generate a proposal for {company} based on the following details:\n"
        f"## Requirements:\n{requirements}\n\n"
        f"## Pricing:\n{pricing}\n\n"
        f"## Services:\n{services}\n\n"
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
    result = ProposalResult.model_validate_json(result_text)
    
    # Save to Cloud Storage
    storage_client = storage.Client(project=project_id)
    bucket_name = f"{project_id}-proposals"
    try:
        bucket = storage_client.get_bucket(bucket_name)
    except Exception:
        # Create bucket if it doesn't exist
        bucket = storage_client.create_bucket(bucket_name, location="US")
        
    timestamp = int(time.time())
    safe_company_name = "".join([c if c.isalnum() else "_" for c in company])
    folder_name = f"{safe_company_name}_{timestamp}"
    
    # Save markdown proposal
    blob_md = bucket.blob(f"{folder_name}/proposal.md")
    blob_md.upload_from_string(result.proposal_markdown, content_type="text/markdown")
    
    # Save pdf content
    blob_pdf = bucket.blob(f"{folder_name}/proposal_pdf_content.txt")
    blob_pdf.upload_from_string(result.pdf_content, content_type="text/plain")
    
    # Save email version
    blob_email = bucket.blob(f"{folder_name}/email.txt")
    blob_email.upload_from_string(result.email_version, content_type="text/plain")
    
    return result

app = proposal_agent

root_agent = app
