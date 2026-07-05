"""Dynamic, GCS-backed agent configuration with TTL caching.

Config resolution order:
  1. TOOLS_CONFIG_GCS_URI env var → load JSON from GCS
  2. Local config/tools_config.json fallback
  3. Environment variable defaults
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
    source: str = "local"
    gcs_uri: Optional[str] = None


class AgentConfig(BaseModel):
    tools: dict[str, ToolConfig] = Field(default_factory=dict)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    settings: dict[str, Any] = Field(default_factory=dict)


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
        self._cached = None
        self._last_loaded = 0.0

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
                    "Failed to load config from GCS (%s): %s — trying local file.",
                    config_uri,
                    exc,
                )
        local_path = os.path.join(os.path.dirname(__file__), "config", "tools_config.json")
        local_path = os.path.normpath(local_path)
        if os.path.exists(local_path):
            try:
                with open(local_path, encoding="utf-8") as f:
                    data = json.load(f)
                cfg = AgentConfig.model_validate(data)
                _resolve_env_refs(cfg)
                logger.info("Loaded agent config from local file: %s", local_path)
                return cfg
            except Exception as exc:
                logger.warning(
                    "Failed to load local config (%s): %s — falling back to env vars.",
                    local_path,
                    exc,
                )
        return _build_from_env()


loader = ConfigLoader()


def get_config() -> AgentConfig:
    return loader.get()


def _resolve_env_refs(cfg: AgentConfig) -> None:
    """Replace 'env:VAR_NAME' strings with actual environment variable values."""
    for tool_cfg in cfg.tools.values():
        for key, value in list(tool_cfg.config.items()):
            if isinstance(value, str) and value.startswith("env:"):
                tool_cfg.config[key] = os.environ.get(value[4:], "")
    for key, value in list(cfg.settings.items()):
        if isinstance(value, str) and value.startswith("env:"):
            cfg.settings[key] = os.environ.get(value[4:], "")


def _build_from_env() -> AgentConfig:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    firestore_collection = os.environ.get("FIRESTORE_USAGE_COLLECTION", "ops_iq_usage")

    tools: dict[str, ToolConfig] = {
        "quota_monitoring": ToolConfig(
            enabled=bool(project),
            config={
                "services": ["aiplatform.googleapis.com"],
                "project": project,
            },
        ),
        "metrics_monitoring": ToolConfig(
            enabled=bool(project),
            config={
                "default_lookback_hours": int(os.environ.get("METRICS_DEFAULT_HOURS", "24")),
                "max_lookback_hours": int(os.environ.get("METRICS_MAX_HOURS", "168")),
            },
        ),
        "vertex_resources": ToolConfig(
            enabled=bool(project),
            config={"location": location},
        ),
        "user_usage_tracking": ToolConfig(
            enabled=bool(project),
            config={
                "firestore_collection": firestore_collection,
                "retention_days": int(os.environ.get("USAGE_RETENTION_DAYS", "90")),
            },
        ),
        "gemini_enterprise": ToolConfig(
            enabled=False,
            config={},
        ),
        "alerting": ToolConfig(
            enabled=bool(project),
            config={
                "email_agent_resource_name": os.environ.get("EMAIL_AGENT_RESOURCE_NAME", ""),
                "from_name": os.environ.get("ALERT_FROM_NAME", "Ops IQ — Stratova AI"),
                "to_emails": os.environ.get("ALERT_TO_EMAILS", ""),
                "thresholds": {
                    "error_rate_pct": 2.0,
                    "latency_p99_ms": 5000,
                    "token_daily_budget": 5_000_000,
                    "request_daily_budget": 10_000,
                    "quota_utilisation_pct": 80.0,
                },
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
