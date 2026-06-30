"""Tool registry — returns the complete list of tool functions.

All tools are always registered with the ADK Agent. Each individual tool
function re-reads the TTL-cached config on every call, so enabling or
disabling a tool in tools_config.json takes effect within
CONFIG_CACHE_TTL_SECONDS without any redeploy.

The dynamic instruction (prompts.py) also injects the current ENABLED /
DISABLED status, so the LLM knows which tools to actually use.
"""
from __future__ import annotations

from typing import Callable

from tools.a2a import a2a_tools
from tools.atlassian import confluence_tool, jira_tool
from tools.google import gemini_connector_tool, gchat_tool, gdrive_tool, gmail_tool
from tools.github import github_tool
from tools.hrm import bamboohr_tool, rippling_tool, workday_tool
from tools.microsoft import sharepoint_tool, onedrive_tool, outlook_tool
from tools.notion import notion_tool
from tools.rag import user_rag_tool
from tools.salesforce import salesforce_tool
from tools.slack import slack_tool
from tools.smartsheet import smartsheet_tool
from tools.support import freshdesk_tool, zendesk_tool
from tools.zoho import books_tool, crm_tool, desk_tool, people_tool


def get_all_tools() -> list[Callable]:
    tools: list[Callable] = []

    # ── Knowledge / RAG ───────────────────────────────────────────────────────
    tools.extend(user_rag_tool.get_tools())

    # ── Google ────────────────────────────────────────────────────────────────
    tools.extend(gemini_connector_tool.get_tools())
    tools.extend(gmail_tool.get_tools())
    tools.extend(gdrive_tool.get_tools())
    tools.extend(gchat_tool.get_tools())

    # ── GitHub ────────────────────────────────────────────────────────────────
    tools.extend(github_tool.get_tools())

    # ── Atlassian (Jira + Confluence) ─────────────────────────────────────────
    tools.extend(jira_tool.get_tools())
    tools.extend(confluence_tool.get_tools())

    # ── Microsoft 365 ─────────────────────────────────────────────────────────
    tools.extend(sharepoint_tool.get_tools())
    tools.extend(onedrive_tool.get_tools())
    tools.extend(outlook_tool.get_tools())

    # ── Notion ────────────────────────────────────────────────────────────────
    tools.extend(notion_tool.get_tools())

    # ── Slack ─────────────────────────────────────────────────────────────────
    tools.extend(slack_tool.get_tools())

    # ── Smartsheet ────────────────────────────────────────────────────────────
    tools.extend(smartsheet_tool.get_tools())

    # ── Salesforce ────────────────────────────────────────────────────────────
    tools.extend(salesforce_tool.get_tools())

    # ── Zoho suite (CRM, Desk, Books, People) ─────────────────────────────────
    tools.extend(crm_tool.get_tools())
    tools.extend(desk_tool.get_tools())
    tools.extend(books_tool.get_tools())
    tools.extend(people_tool.get_tools())

    # ── Support (FreshDesk, Zendesk) ──────────────────────────────────────────
    tools.extend(freshdesk_tool.get_tools())
    tools.extend(zendesk_tool.get_tools())

    # ── HRM (WorkDay, BambooHR, Rippling) ─────────────────────────────────────
    tools.extend(workday_tool.get_tools())
    tools.extend(bamboohr_tool.get_tools())
    tools.extend(rippling_tool.get_tools())

    # ── A2A tools — route to independently deployed agents ────────────────────
    tools.extend(a2a_tools.get_tools())

    return tools
