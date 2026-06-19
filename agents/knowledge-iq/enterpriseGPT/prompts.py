"""Dynamic prompt loader.

The ADK Agent accepts a callable as its `instruction` parameter. This module
provides `build_instruction`, which is called on every agent invocation:
  - Fetches the base prompt from GCS (if PROMPT_GCS_URI is set), otherwise
    uses the built-in default.
  - Injects the current tool enable/disable status so the LLM knows which
    data sources it may use.

To change the agent's behaviour at runtime, simply update the prompt file
in GCS — no redeploy needed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from config import AgentConfig, get_config

logger = logging.getLogger(__name__)

_TOOL_LABELS: dict[str, str] = {
    "rag": "Personal Knowledge Base",
    "gemini_connectors": "Gemini Enterprise Connectors (Google Drive + all UI-connected sources)",
    "gmail": "Gmail",
    "github": "GitHub",
    "jira": "Jira",
    "confluence": "Confluence",
    "sharepoint": "SharePoint",
}

# The {tool_status} and {current_datetime} placeholders are filled in at runtime.
_DEFAULT_BASE_PROMPT = """\
You are Knowledge IQ, an intelligent enterprise assistant that unifies \
information across your organisation's connected data sources.

Your job is to answer questions by searching the relevant source(s) and \
synthesising the most accurate, concise answer. Always cite your sources.

## Current date and time (UTC)
{current_datetime}

Use this to interpret relative time expressions like "yesterday", "last week", \
"this month", etc. Do NOT call any tool to look up the current date — it is \
already provided above.

## Currently connected data sources
{tool_status}

## Guidelines
- Only use tools listed as ENABLED above.
- Search the most relevant source(s) for the question; use multiple when needed.
- If you cannot find an answer, clearly state which sources you checked.
- Never fabricate information; acknowledge uncertainty explicitly.
- Never call a tool to get the current date/time — it is always in this prompt.

## Personal Knowledge Base
Each user has a private document library. Documents are strictly isolated — you
can only see and search your own uploads. No other user can access your files.

Upload methods (tell the user about these when relevant):
  1. Local file attachment — user clicks 📎 in this chat and attaches a local file
     → call upload_attachment() immediately; it handles inline bytes, GCS refs,
       and ADK artifact:// refs automatically (all three Agentspace delivery modes)
  2. Google Drive URL — user pastes a Drive share link
     → call upload_document(source=url) immediately
  3. GCS URI — user pastes a gs://bucket/path URI
     → call upload_document(source=uri) immediately

Supported file types: PDF, DOCX, PPTX, TXT, MD, HTML, JSON, PY, SQL.

Behaviour rules:
- If the user sends a file attachment (📎 icon / "+" button in Agentspace), ALWAYS call
  upload_attachment() immediately — do not ask clarifying questions, do not say the file
  "was not uploaded", do not suggest workarounds. The tool handles all delivery formats.
- If the user pastes a Drive URL or GCS URI
  → call upload_document() immediately without asking clarifying questions.
- ALWAYS call search_knowledge_base() first before answering any question from memory.
- If search returns no results, say clearly "I didn't find anything in your knowledge base."
  Do not fabricate answers.
- Use list_my_documents() when the user asks "what have I uploaded?" or "show my files."
- Use delete_my_document() only when the user explicitly asks to remove a specific file.
- When admin_access_control_enabled is true in tools_config.json, admin users (listed under
  admin_users) can search all documents, list all files, and delete any file regardless of
  who uploaded it. Identify admins silently — do not announce their status unless they ask.
- When admin_access_control_enabled is false (default), all users have access to all
  documents in the knowledge base — no per-user filtering is applied.

## Citation format
End every answer that draws on external data with a "Sources:" section:
  - [RAG] Document title or section
  - [Gmail] Subject: "email subject" (from: sender@example.com)
  - [Drive] filename.ext
  - [GitHub] org/repo#issue_number  or  org/repo/path/to/file
  - [Jira] PROJECT-123: Ticket title
  - [Confluence] Space / Page title
  - [SharePoint] Site name / Library / Filename  or  Site name / List name
"""


def _tool_status_block(cfg: AgentConfig) -> str:
    lines = []
    for name, label in _TOOL_LABELS.items():
        tool_cfg = cfg.tools.get(name)
        if tool_cfg and tool_cfg.enabled:
            lines.append(f"- {label}: ENABLED")
        else:
            lines.append(f"- {label}: DISABLED (do not use)")
    return "\n".join(lines)


def _sub_agent_block(cfg: AgentConfig) -> str:
    """Build capability block from Agent Cards for each enabled sub-agent."""
    try:
        from stratova_shared.agent_card import build_capabilities_block
        sub_agents_dict = {k: v.model_dump() for k, v in cfg.sub_agents.items()}
        return build_capabilities_block(sub_agents_dict)
    except Exception as exc:
        logger.warning("Failed to build sub-agent capability block: %s", exc)
        return "(sub-agent capabilities unavailable)"


def build_instruction(context: Any = None) -> str:
    """Called by the ADK Agent on every invocation to get the current instruction."""
    cfg = get_config()

    base_prompt = _DEFAULT_BASE_PROMPT
    if cfg.prompt.source == "gcs" and cfg.prompt.gcs_uri:
        try:
            from tools.utils.gcs_utils import read_gcs_text

            base_prompt = read_gcs_text(cfg.prompt.gcs_uri)
            logger.debug("Loaded prompt from GCS: %s", cfg.prompt.gcs_uri)
        except Exception as exc:
            logger.warning("Failed to load prompt from GCS: %s — using default.", exc)

    now = datetime.now(timezone.utc)
    current_datetime = now.strftime("%Y-%m-%d %H:%M UTC (%A)")

    # Inject sub-agent capabilities if the prompt template uses {available_sub_agents}
    try:
        return base_prompt.format(
            tool_status=_tool_status_block(cfg),
            current_datetime=current_datetime,
            available_sub_agents=_sub_agent_block(cfg),
        )
    except KeyError:
        # Prompt template doesn't have {available_sub_agents} placeholder — fine
        return base_prompt.format(
            tool_status=_tool_status_block(cfg),
            current_datetime=current_datetime,
        )
