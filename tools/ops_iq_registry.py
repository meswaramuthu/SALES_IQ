"""Tool registry for Ops IQ — returns all GCP monitoring tool functions.

All tools are always registered with the ADK Agent. Each individual tool
function re-reads the TTL-cached config on every call, so enabling or
disabling a tool in tools_config.json takes effect within
CONFIG_CACHE_TTL_SECONDS without any redeploy.

The dynamic instruction (prompts.py) also injects the current ENABLED /
DISABLED status, so the LLM knows which tools to actually use.
"""
from __future__ import annotations

from typing import Callable

from tools.google import metrics_tool, quota_tool
from tools.vertex import vertex_resources_tool
from tools.firestore import usage_tracker_tool
from tools.alerting import alerting_tool


def get_all_tools() -> list[Callable]:
    tools: list[Callable] = []
    tools.extend(quota_tool.get_tools())
    tools.extend(metrics_tool.get_tools())
    tools.extend(vertex_resources_tool.get_tools())
    tools.extend(usage_tracker_tool.get_tools())
    tools.extend(alerting_tool.get_tools())
    return tools
