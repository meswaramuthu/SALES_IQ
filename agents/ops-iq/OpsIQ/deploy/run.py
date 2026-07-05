"""Quick smoke-test for the deployed Ops IQ agent."""
import os

import vertexai
from dotenv import load_dotenv
from vertexai import agent_engines

load_dotenv()

GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
AGENT_ENGINE_ID = os.getenv("AGENT_ENGINE_ID")

if not AGENT_ENGINE_ID:
    raise SystemExit("AGENT_ENGINE_ID is not set in .env")

vertexai.init(project=GOOGLE_CLOUD_PROJECT, location=GOOGLE_CLOUD_LOCATION)

agent = agent_engines.get(AGENT_ENGINE_ID)
session = agent.create_session(user_id="test-user")

TEST_QUERIES = [
    "Give me a quota headroom summary for Vertex AI.",
    "How many tokens did we use in the last 24 hours?",
    "List all deployed Vertex AI Agent Engines.",
    "Are there any elevated error rates right now?",
    "Give me a full platform health report.",
]

for query in TEST_QUERIES:
    print(f"\n{'='*60}")
    print(f"User: {query}")
    print("Agent: ", end="", flush=True)
    for event in agent.stream_query(session_id=session["id"], message=query):
        for part in event.get("content", {}).get("parts", []):
            if "text" in part:
                print(part["text"], end="", flush=True)
    print()
