"""Register Knowledge-IQ agents in Gemini Enterprise (Vertex AI Agentspace).

This script:
  1. Updates Agent Engine display names and descriptions for all 4 agents
  2. Creates Agentspace chat engines in Discovery Engine so agents appear
     in the Google Cloud Console's Agent Builder / Agentspace UI

Run from inside the enterpriseGPT uv environment:
    cd agents/knowledge-iq/enterpriseGPT
    uv run python ../deploy/register_gemini_enterprise.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import vertexai
from dotenv import load_dotenv
from vertexai import agent_engines

# Load env from enterpriseGPT (has project/location)
_SCRIPT_DIR = Path(__file__).parent.resolve()
_KIQ_DIR    = _SCRIPT_DIR.parent.resolve()
load_dotenv(_KIQ_DIR / "enterpriseGPT" / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT  = os.getenv("GOOGLE_CLOUD_PROJECT", "ninth-archway-496404-s2")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET   = os.getenv("STAGING_BUCKET", "gs://stratova-platform")

# ── Agent catalogue ─────────────────────────────────────────────────────────
AGENTS = [
    {
        "resource_name": "projects/528271267622/locations/us-central1/reasoningEngines/7954287678529208320",
        "display_name": "Laabu Enterprise Search",
        "agentspace_id": "laabu-kiq-enterprise-search",
        "description": (
            "Enterprise knowledge search and retrieval across all organisational data sources: "
            "RAG corpus, Gmail, Google Drive, Jira, Confluence, GitHub, SharePoint, OneDrive, "
            "Outlook, and Notion. Surfaces grounded answers with source citations."
        ),
    },
    {
        "resource_name": "projects/528271267622/locations/us-central1/reasoningEngines/8073633068654526464",
        "display_name": "Laabu Document Intelligence",
        "agentspace_id": "laabu-kiq-document-intelligence",
        "description": (
            "Intelligent document ingestion for the organisational knowledge base. "
            "AI-analyses content, suggests metadata tags, confirms accessibility scope "
            "(organisation-wide, department-restricted, or personal-private), and ingests "
            "documents into the RAG corpus with full provenance tracking."
        ),
    },
    {
        "resource_name": "projects/528271267622/locations/us-central1/reasoningEngines/2437378135000350720",
        "display_name": "Laabu Knowledge IQ Hub",
        "agentspace_id": "laabu-kiq-orchestrator-hub",
        "description": (
            "Central routing hub for all Knowledge IQ operations. Intelligently routes "
            "document upload requests to the Document Intelligence agent and knowledge "
            "search queries to the Enterprise Search agent. The primary entry point for "
            "any agent or system that needs to interact with the knowledge base."
        ),
    },
    {
        "resource_name": "projects/528271267622/locations/us-central1/reasoningEngines/6697783382492839936",
        "display_name": "Laabu Personal Copilot",
        "agentspace_id": "laabu-kiq-personal-copilot",
        "description": (
            "A private AI copilot for every employee. Answers general questions, drafts and "
            "summarises content, and searches documents the user has personally uploaded — "
            "with strict per-user file isolation so no one can see another user's documents. "
            "Uploads to the user's private knowledge base via the Document Intelligence agent."
        ),
    },
]


def step1_update_agent_engine_metadata() -> None:
    """Update Agent Engine display_name and description for all 4 agents."""
    log.info("Step 1: Updating Agent Engine display names and descriptions …")
    vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=BUCKET)

    for a in AGENTS:
        try:
            engine = agent_engines.get(a["resource_name"])
            engine.update(
                display_name=a["display_name"],
                description=a["description"],
            )
            log.info("  ✓ %-45s → '%s'", a["resource_name"].split("/")[-1], a["display_name"])
        except Exception as exc:
            log.warning("  ✗ Failed to update %s: %s", a["display_name"], exc)


def step2_register_agentspace_engines() -> None:
    """Create/update Agentspace chat engines in Discovery Engine."""
    log.info("Step 2: Registering agents in Gemini Enterprise (Agentspace) …")

    try:
        from google.cloud import discoveryengine_v1alpha as de
    except ImportError:
        log.error("google-cloud-discoveryengine not installed — skipping Agentspace registration.")
        return

    client = de.EngineServiceClient()
    parent = f"projects/{PROJECT}/locations/global/collections/default_collection"

    for a in AGENTS:
        engine_id = a["agentspace_id"]
        engine_name = f"{parent}/engines/{engine_id}"

        # Check if engine already exists
        try:
            existing = client.get_engine(name=engine_name)
            log.info("  ~ Engine '%s' already exists — updating display name.", engine_id)
            updated = de.Engine(
                name=engine_name,
                display_name=a["display_name"],
            )
            client.update_engine(
                engine=updated,
                update_mask={"paths": ["display_name"]},
            )
            log.info("  ✓ Updated: %s", engine_id)
            continue
        except Exception:
            pass  # Engine doesn't exist, create it

        # Create new engine
        try:
            engine = de.Engine(
                display_name=a["display_name"],
                solution_type=de.SolutionType.SOLUTION_TYPE_CHAT,
                chat_engine_config=de.Engine.ChatEngineConfig(
                    agent_creation_config=de.Engine.ChatEngineConfig.AgentCreationConfig(
                        business=f"Laabu — Knowledge IQ",
                        default_language_code="en",
                        time_zone="UTC",
                    )
                ),
                common_config=de.Engine.CommonConfig(
                    company_name="Laabu",
                ),
            )
            op = client.create_engine(
                parent=parent,
                engine=engine,
                engine_id=engine_id,
            )
            result = op.result(timeout=120)
            log.info("  ✓ Created Agentspace engine: %s → '%s'", engine_id, a["display_name"])
        except Exception as exc:
            log.warning("  ✗ Could not create engine '%s': %s", engine_id, exc)


def main() -> None:
    log.info("=" * 60)
    log.info("  Knowledge IQ — Gemini Enterprise Registration")
    log.info("  Project : %s", PROJECT)
    log.info("  Location: %s", LOCATION)
    log.info("=" * 60)

    step1_update_agent_engine_metadata()
    log.info("")
    step2_register_agentspace_engines()

    log.info("")
    log.info("=" * 60)
    log.info("  Agent Engine display names and Agentspace engines updated.")
    log.info("  View at:")
    log.info("  https://console.cloud.google.com/vertex-ai/reasoning-engines")
    log.info("  https://console.cloud.google.com/ai/agentspace")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
