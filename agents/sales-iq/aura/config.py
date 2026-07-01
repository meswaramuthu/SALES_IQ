"""AURA Sales IQ — Orchestrator: Dynamic, GCS-backed agent configuration with TTL caching.

The agent re-reads tools_config.json from GCS every CONFIG_CACHE_TTL_SECONDS
seconds (default 60). This means you can enable/disable any sales tool
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
        "crm": ToolConfig(
            enabled=bool(os.environ.get("CRM_ENABLED", "false").lower() == "true"),
            config={
                "hubspot_api_key": os.environ.get("HUBSPOT_API_KEY", ""),
                "salesforce_instance_url": os.environ.get("SALESFORCE_INSTANCE_URL", ""),
                "salesforce_access_token": os.environ.get("SALESFORCE_ACCESS_TOKEN", ""),
                "default_crm": os.environ.get("DEFAULT_CRM", "hubspot"),
            },
        ),
        "calendar": ToolConfig(
            enabled=os.environ.get("CALENDAR_ENABLED", "false").lower() == "true",
            config={
                "service_account_key_gcs_uri": os.environ.get("CALENDAR_SA_KEY_GCS_URI", ""),
                "user_email": os.environ.get("CALENDAR_USER_EMAIL", ""),
                "calendar_id": os.environ.get("GOOGLE_CALENDAR_ID", "primary"),
                "timezone": os.environ.get("CALENDAR_TIMEZONE", "UTC"),
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
        "apollo": ToolConfig(
            enabled=os.environ.get("APOLLO_ENABLED", "false").lower() == "true",
            config={
                "api_key": os.environ.get("APOLLO_API_KEY", ""),
                "max_results": int(os.environ.get("APOLLO_MAX_RESULTS", "25")),
            },
        ),
        "linkedin": ToolConfig(
            enabled=os.environ.get("LINKEDIN_ENABLED", "false").lower() == "true",
            config={
                "client_id": os.environ.get("LINKEDIN_CLIENT_ID", ""),
                "client_secret": os.environ.get("LINKEDIN_CLIENT_SECRET", ""),
                "access_token": os.environ.get("LINKEDIN_ACCESS_TOKEN", ""),
            },
        ),
        "clearbit": ToolConfig(
            enabled=os.environ.get("CLEARBIT_ENABLED", "false").lower() == "true",
            config={
                "api_key": os.environ.get("CLEARBIT_API_KEY", ""),
            },
        ),
        "docusign": ToolConfig(
            enabled=os.environ.get("DOCUSIGN_ENABLED", "false").lower() == "true",
            config={
                "account_id": os.environ.get("DOCUSIGN_ACCOUNT_ID", ""),
                "integration_key": os.environ.get("DOCUSIGN_INTEGRATION_KEY", ""),
                "user_id": os.environ.get("DOCUSIGN_USER_ID", ""),
                "rsa_private_key_gcs_uri": os.environ.get("DOCUSIGN_RSA_KEY_GCS_URI", ""),
                "base_path": os.environ.get("DOCUSIGN_BASE_PATH", "https://demo.docusign.net/restapi"),
            },
        ),
        "slack": ToolConfig(
            enabled=os.environ.get("SLACK_ENABLED", "false").lower() == "true",
            config={
                "bot_token": os.environ.get("SLACK_BOT_TOKEN", ""),
                "default_channel": os.environ.get("SLACK_DEFAULT_CHANNEL", "#sales"),
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
