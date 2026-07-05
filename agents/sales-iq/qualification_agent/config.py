"""Dynamic, GCS-backed agent configuration with TTL caching.

The agent re-reads tools_config.json from GCS every CONFIG_CACHE_TTL_SECONDS
seconds (default 60). This means you can enable/disable any data-source tool
or change the prompt GCS URI at runtime without restarting the agent.

Config resolution order:
  1. TOOLS_CONFIG_GCS_URI env var → load JSON from GCS
  2. Fallback → build config from individual env vars (see .env.example)
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

CONFIG_CACHE_TTL_SECONDS: float = float(os.environ.get("CONFIG_CACHE_TTL_SECONDS", "60"))


class ToolConfig(BaseModel):
    enabled: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class PromptConfig(BaseModel):
    # "local" uses the built-in default prompt; "gcs" fetches from gcs_uri.
    source: str = "local"
    gcs_uri: Optional[str] = None


class SubAgentConfig(BaseModel):
    enabled: bool = False
    resource_name: str = ""
    agent_card_url: str = ""
    description: str = ""


class AgentConfig(BaseModel):
    tools: dict[str, ToolConfig] = Field(default_factory=dict)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    sub_agents: dict[str, SubAgentConfig] = Field(default_factory=dict)


class ConfigLoader:
    """Thread-safe TTL-cached loader. One module-level instance is shared."""

    def __init__(self) -> None:
        self._cached: Optional[AgentConfig] = None
        self._last_loaded: float = 0.0

    def get(self) -> AgentConfig:
        now = time.monotonic()
        if self._cached is None or (now - self._last_loaded) > CONFIG_CACHE_TTL_SECONDS:
            self._cached = self._load()
            self._last_loaded = now
        return self._cached

    def invalidate(self) -> None:
        """Force a config reload on the next call to get()."""
        self._cached = None
        self._last_loaded = 0.0

    # ------------------------------------------------------------------
    def _load(self) -> AgentConfig:
        config_uri = os.environ.get("TOOLS_CONFIG_GCS_URI")
        if config_uri:
            try:
                from tools.utils.gcs_utils import read_gcs_text

                data = json.loads(read_gcs_text(config_uri))
                cfg = AgentConfig.model_validate(data)
                _resolve_env_refs(cfg)
                logger.info("Loaded agent config from GCS: %s", config_uri)
                return cfg
            except Exception as exc:
                logger.warning(
                    "Failed to load config from GCS (%s): %s — falling back to env vars.",
                    config_uri,
                    exc,
                )
        return _build_from_env()


# Module-level singleton — imported by all tool modules.
loader = ConfigLoader()


def get_config() -> AgentConfig:
    return loader.get()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _resolve_env_refs(cfg: AgentConfig) -> None:
    """Replace "env:VAR_NAME" values with the actual environment variable."""
    for tool_cfg in cfg.tools.values():
        for key, value in list(tool_cfg.config.items()):
            if isinstance(value, str) and value.startswith("env:"):
                tool_cfg.config[key] = os.environ.get(value[4:], "")


def _build_from_env() -> AgentConfig:
    tools: dict[str, ToolConfig] = {
        "rag": ToolConfig(
            enabled=bool(os.environ.get("RAG_CORPUS")),
            config={
                "corpus": os.environ.get("RAG_CORPUS", ""),
                "embedding_model": os.environ.get(
                    "RAG_EMBEDDING_MODEL",
                    "publishers/google/models/text-embedding-004",
                ),
                "chunk_size": int(os.environ.get("RAG_CHUNK_SIZE", "512")),
                "chunk_overlap": int(os.environ.get("RAG_CHUNK_OVERLAP", "100")),
                "similarity_top_k": int(os.environ.get("RAG_SIMILARITY_TOP_K", "10")),
                "vector_distance_threshold": float(os.environ.get("RAG_DISTANCE_THRESHOLD", "0.6")),
                "user_file_registry_uri": os.environ.get(
                    "USER_FILE_REGISTRY_URI",
                    "gs://stratova-platform/knowledge-iq/user_file_registry.json",
                ),
                "admin_access_control_enabled": os.environ.get(
                    "RAG_ADMIN_ACCESS_CONTROL_ENABLED", "false"
                ).lower() == "true",
                "admin_users": [
                    u.strip()
                    for u in os.environ.get("RAG_ADMIN_USERS", "").split(",")
                    if u.strip()
                ],
            },
        ),
        "gmail": ToolConfig(
            enabled=os.environ.get("GMAIL_ENABLED", "false").lower() == "true",
            config={
                "service_account_key_gcs_uri": os.environ.get("GMAIL_SA_KEY_GCS_URI", ""),
                "user_email": os.environ.get("GMAIL_USER_EMAIL", ""),
                "max_results": int(os.environ.get("GMAIL_MAX_RESULTS", "20")),
            },
        ),
        "gdrive": ToolConfig(
            enabled=os.environ.get("GDRIVE_ENABLED", "false").lower() == "true",
            config={
                "service_account_key_gcs_uri": os.environ.get("GDRIVE_SA_KEY_GCS_URI", ""),
                "user_email": os.environ.get("GDRIVE_USER_EMAIL", ""),
            },
        ),
        "github": ToolConfig(
            enabled=os.environ.get("GITHUB_ENABLED", "false").lower() == "true",
            config={
                "token": os.environ.get("GITHUB_TOKEN", ""),
                "default_org": os.environ.get("GITHUB_DEFAULT_ORG", ""),
            },
        ),
        "jira": ToolConfig(
            enabled=os.environ.get("JIRA_ENABLED", "false").lower() == "true",
            config={
                "url": os.environ.get("JIRA_URL", ""),
                "username": os.environ.get("JIRA_USERNAME", ""),
                "api_token": os.environ.get("JIRA_API_TOKEN", ""),
            },
        ),
        "confluence": ToolConfig(
            enabled=os.environ.get("CONFLUENCE_ENABLED", "false").lower() == "true",
            config={
                "url": os.environ.get("CONFLUENCE_URL", ""),
                "username": os.environ.get("CONFLUENCE_USERNAME", ""),
                "api_token": os.environ.get("CONFLUENCE_API_TOKEN", ""),
            },
        ),
        "sharepoint": ToolConfig(
            enabled=os.environ.get("SHAREPOINT_ENABLED", "false").lower() == "true",
            config={
                "tenant_id": os.environ.get("SHAREPOINT_TENANT_ID", ""),
                "client_id": os.environ.get("SHAREPOINT_CLIENT_ID", ""),
                "client_secret": os.environ.get("SHAREPOINT_CLIENT_SECRET", ""),
                "site_url": os.environ.get("SHAREPOINT_SITE_URL", ""),
                "search_region": os.environ.get("SHAREPOINT_SEARCH_REGION", "APC"),
            },
        ),
        "onedrive": ToolConfig(
            enabled=os.environ.get("ONEDRIVE_ENABLED", "false").lower() == "true",
            config={
                "tenant_id": os.environ.get("ONEDRIVE_TENANT_ID", ""),
                "client_id": os.environ.get("ONEDRIVE_CLIENT_ID", ""),
                "client_secret": os.environ.get("ONEDRIVE_CLIENT_SECRET", ""),
                "user_email": os.environ.get("ONEDRIVE_USER_EMAIL", ""),
            },
        ),
        "outlook": ToolConfig(
            enabled=os.environ.get("OUTLOOK_ENABLED", "false").lower() == "true",
            config={
                "tenant_id": os.environ.get("OUTLOOK_TENANT_ID", ""),
                "client_id": os.environ.get("OUTLOOK_CLIENT_ID", ""),
                "client_secret": os.environ.get("OUTLOOK_CLIENT_SECRET", ""),
                "user_email": os.environ.get("OUTLOOK_USER_EMAIL", ""),
            },
        ),
        "notion": ToolConfig(
            enabled=os.environ.get("NOTION_ENABLED", "false").lower() == "true",
            config={
                "api_token": os.environ.get("NOTION_API_TOKEN", ""),
            },
        ),
    }
    return AgentConfig(
        tools=tools,
        prompt=PromptConfig(
            source="gcs" if os.environ.get("PROMPT_GCS_URI") else "local",
            gcs_uri=os.environ.get("PROMPT_GCS_URI"),
        ),
    )
