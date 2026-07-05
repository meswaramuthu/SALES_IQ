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

def save_qualification_result(
    company_name: str,
    budget_score: int,
    authority_score: int,
    need_score: int,
    timeline_score: int,
    status: Literal["qualified", "warm", "cold"],
    notes: str
) -> str:
    """Saves the final qualification result of a prospect to the database. Use this after analyzing a prospect."""
    db = firestore.Client(project=project_id)
    
    if status == "qualified":
        collection_name = "Qualified_proposal"
    else:
        collection_name = "Unqualified_proposal"
        
    doc_ref = db.collection("AURA_internal").document("records").collection(collection_name).document()
    doc_ref.set({
        "company_name": company_name,
        "budget_score": budget_score,
        "authority_score": authority_score,
        "need_score": need_score,
        "timeline_score": timeline_score,
        "status": status,
        "notes": notes
    })
    
    return f"Successfully saved {company_name} to {collection_name}."

qualification_agent = Agent(
    model="gemini-2.5-flash",
    name="qualification_agent",
    instruction=SYSTEM_PROMPT,
    tools=[save_qualification_result],
)

app = qualification_agent

root_agent = app
