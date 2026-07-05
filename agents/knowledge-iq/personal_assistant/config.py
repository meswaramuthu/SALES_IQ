"""Dynamic, GCS-backed config loader for the Personal Assistant agent."""
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
        local_path = os.path.join(os.path.dirname(__file__), "config", "tools_config.json")
        if os.environ.get("USE_LOCAL_CONFIG") == "1" and os.path.isfile(local_path):
            try:
                with open(local_path) as f:
                    data = json.load(f)
                cfg = AgentConfig.model_validate(data)
                _resolve_env_refs(cfg)
                logger.info("Loaded personal_assistant config from local file: %s", local_path)
                return cfg
            except Exception as exc:
                logger.warning(
                    "Local config load failed (%s): %s — falling back to GCS.", local_path, exc
                )

        config_uri = os.environ.get("TOOLS_CONFIG_GCS_URI")
        if config_uri:
            try:
                from tools.utils.gcs_utils import read_gcs_text
                data = json.loads(read_gcs_text(config_uri))
                cfg = AgentConfig.model_validate(data)
                _resolve_env_refs(cfg)
                logger.info("Loaded personal_assistant config from GCS: %s", config_uri)
                return cfg
            except Exception as exc:
                logger.warning(
                    "GCS config load failed (%s): %s — falling back to env vars.", config_uri, exc
                )

        return _build_from_env()


loader = ConfigLoader()


def get_config() -> AgentConfig:
    return loader.get()


def _resolve_env_refs(cfg: AgentConfig) -> None:
    for tool_cfg in cfg.tools.values():
        for key, value in list(tool_cfg.config.items()):
            if isinstance(value, str) and value.startswith("env:"):
                tool_cfg.config[key] = os.environ.get(value[4:], "")
    for sa_cfg in cfg.sub_agents.values():
        if sa_cfg.resource_name.startswith("env:"):
            sa_cfg.resource_name = os.environ.get(sa_cfg.resource_name[4:], "")
        if sa_cfg.agent_card_url.startswith("env:"):
            sa_cfg.agent_card_url = os.environ.get(sa_cfg.agent_card_url[4:], "")


def _build_from_env() -> AgentConfig:
    tools: dict[str, ToolConfig] = {}

    corpus = os.environ.get("RAG_CORPUS", "")
    personal_registry_uri = os.environ.get(
        "PERSONAL_REGISTRY_URI",
        "gs://stratova-platform/knowledge-iq/personal_file_registry.json",
    )
    if corpus:
        tools["rag"] = ToolConfig(
            enabled=True,
            config={
                "corpus": corpus,
                "personal_registry_uri": personal_registry_uri,
                "similarity_top_k": 5,
                "vector_distance_threshold": 0.6,
            },
        )

    sub_agents: dict[str, SubAgentConfig] = {}
    dm_resource = os.environ.get("DOCUMENT_MINING_AGENT_RESOURCE_NAME", "")
    if dm_resource:
        sub_agents["document_mining_agent"] = SubAgentConfig(
            enabled=True,
            resource_name=dm_resource,
            description=(
                "Handles document analysis and upload to the personal knowledge base."
            ),
        )

    return AgentConfig(
        tools=tools,
        prompt=PromptConfig(
            source="gcs" if os.environ.get("PROMPT_GCS_URI") else "local",
            gcs_uri=os.environ.get("PROMPT_GCS_URI"),
        ),
        sub_agents=sub_agents,
    )
