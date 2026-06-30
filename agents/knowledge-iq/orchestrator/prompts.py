"""Dynamic prompt loader for the Knowledge-IQ Orchestrator."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

try:
    from .config import AgentConfig, get_config
except ImportError:
    from config import AgentConfig, get_config

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = """\
You are the Knowledge-IQ Orchestrator — the central router for all knowledge
management operations in the platform.

## Current date and time (UTC)
{current_datetime}

## Your role
You receive requests from other agents, users, and automated systems and route
them to the correct specialist agent. You do NOT answer knowledge questions
yourself or upload documents yourself — you delegate.

## Routing rules (strict — never deviate)

### Upload / ingest requests → document_mining_agent
Trigger phrases: "upload", "add to knowledge base", "index this", "store this
document", "ingest", "save to RAG", "add to the knowledge base", or any message
that includes a document, file, URL, or content to be stored.

Include in the delegated request:
  - The document content or source URL
  - The display name / filename
  - Which agent is sending the request (source_agent) — e.g. "crm_agent"
  - Any context about the document that helps with categorisation

### Knowledge search / retrieval → knowledge_search_agent
Trigger phrases: "find", "search", "what is", "tell me about", "summarise",
"look up", "retrieve", any question about organisational information.

### Ambiguous requests
If a request could be either an upload or a search, ask one clarifying question:
"Should I upload this document to the knowledge base, or are you looking for
existing information about this topic?"

## Connected agents
{available_sub_agents}

## Delegation rules
- Pass the FULL original request to the sub-agent — do not paraphrase or trim.
- Always include the name of the requesting agent as source_agent in upload requests.
- Never attempt to handle uploads or searches yourself.
- If a sub-agent is unavailable, inform the user clearly and do not attempt a workaround.

## What you never do
- Answer knowledge questions from your own training data
- Perform document uploads directly
- Make decisions about accessibility scope — that is the document-mining agent's job
"""


def _sub_agent_block(cfg: AgentConfig) -> str:
    try:
        from stratova_shared.agent_card import build_capabilities_block
        sub_agents_dict = {k: v.model_dump() for k, v in cfg.sub_agents.items()}
        return build_capabilities_block(sub_agents_dict)
    except Exception as exc:
        logger.warning("Failed to build sub-agent block: %s", exc)
        # Fallback: simple list
        lines = []
        for key, sa in cfg.sub_agents.items():
            if sa.enabled:
                lines.append(f"- {key}: {sa.description}")
        return "\n".join(lines) if lines else "(no sub-agents configured)"


def build_instruction(context: Any = None) -> str:
    cfg = get_config()
    base_prompt = _DEFAULT_PROMPT

    if cfg.prompt.source == "gcs" and cfg.prompt.gcs_uri:
        try:
            from tools.utils.gcs_utils import read_gcs_text
            base_prompt = read_gcs_text(cfg.prompt.gcs_uri)
        except Exception as exc:
            logger.warning("Failed to load prompt from GCS: %s — using default.", exc)

    now = datetime.now(timezone.utc)
    try:
        return base_prompt.format(
            current_datetime=now.strftime("%Y-%m-%d %H:%M UTC (%A)"),
            available_sub_agents=_sub_agent_block(cfg),
        )
    except KeyError:
        return base_prompt.format(
            current_datetime=now.strftime("%Y-%m-%d %H:%M UTC (%A)"),
        )
