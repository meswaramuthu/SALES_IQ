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
from tools.google import gemini_connector_tool, gdrive_tool, gmail_tool
from tools.github import github_tool
from tools.microsoft import sharepoint_tool, onedrive_tool, outlook_tool
from tools.notion import notion_tool
from tools.rag import user_rag_tool


def get_all_tools() -> list[Callable]:
    tools: list[Callable] = []
    tools.extend(user_rag_tool.get_tools())
    tools.extend(gemini_connector_tool.get_tools())
    tools.extend(gmail_tool.get_tools())
    tools.extend(gdrive_tool.get_tools())
    tools.extend(github_tool.get_tools())
    tools.extend(jira_tool.get_tools())
    tools.extend(confluence_tool.get_tools())
    tools.extend(sharepoint_tool.get_tools())
    tools.extend(onedrive_tool.get_tools())
    tools.extend(outlook_tool.get_tools())
    tools.extend(notion_tool.get_tools())
    # A2A tools — route to independently deployed CRM, Enrichment, WebScraper agents
    tools.extend(a2a_tools.get_tools())
    return tools
