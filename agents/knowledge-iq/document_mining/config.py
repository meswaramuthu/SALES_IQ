"""Dynamic, GCS-backed config loader for the document-mining agent.

Same TTL-caching pattern as enterpriseGPT: reads tools_config.json from GCS
every CONFIG_CACHE_TTL_SECONDS, falls back to env vars on failure or absence.
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

_DEFAULT_SCOPE_REGISTRY_URI = "gs://stratova-platform/knowledge-iq/scope_file_registry.json"


class ToolConfig(BaseModel):
    enabled: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class PromptConfig(BaseModel):
    source: str = "local"
    gcs_uri: Optional[str] = None


class AgentConfig(BaseModel):
    tools: dict[str, ToolConfig] = Field(default_factory=dict)
    prompt: PromptConfig = Field(default_factory=PromptConfig)


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
        # When USE_LOCAL_CONFIG=1, skip GCS and load from the local config file.
        local_path = os.path.join(os.path.dirname(__file__), "config", "tools_config.json")
        if os.environ.get("USE_LOCAL_CONFIG") == "1" and os.path.isfile(local_path):
            try:
                with open(local_path) as f:
                    data = json.load(f)
                cfg = AgentConfig.model_validate(data)
                _resolve_env_refs(cfg)
                logger.info("Loaded document-mining config from local file: %s", local_path)
                return cfg
            except Exception as exc:
                logger.warning("Local config load failed (%s): %s — falling back to GCS.", local_path, exc)

        config_uri = os.environ.get("TOOLS_CONFIG_GCS_URI")
        if config_uri:
            try:
                from tools.utils.gcs_utils import read_gcs_text
                data = json.loads(read_gcs_text(config_uri))
                cfg = AgentConfig.model_validate(data)
                _resolve_env_refs(cfg)
                logger.info("Loaded document-mining config from GCS: %s", config_uri)
                return cfg
            except Exception as exc:
                logger.warning("GCS config load failed (%s): %s — falling back to env vars.", config_uri, exc)
        return _build_from_env()


loader = ConfigLoader()


def get_config() -> AgentConfig:
    return loader.get()


def _resolve_env_refs(cfg: AgentConfig) -> None:
    for tool_cfg in cfg.tools.values():
        for key, value in list(tool_cfg.config.items()):
            if isinstance(value, str) and value.startswith("env:"):
                tool_cfg.config[key] = os.environ.get(value[4:], "")


def _build_from_env() -> AgentConfig:
    return AgentConfig(
        tools={
            "rag": ToolConfig(
                enabled=bool(os.environ.get("RAG_CORPUS")),
                config={
                    "corpus": os.environ.get("RAG_CORPUS", ""),
                    "chunk_size": int(os.environ.get("RAG_CHUNK_SIZE", "512")),
                    "chunk_overlap": int(os.environ.get("RAG_CHUNK_OVERLAP", "100")),
                    "scope_registry_uri": os.environ.get(
                        "SCOPE_REGISTRY_URI", _DEFAULT_SCOPE_REGISTRY_URI
                    ),
                },
            ),
        },
        prompt=PromptConfig(
            source="gcs" if os.environ.get("PROMPT_GCS_URI") else "local",
            gcs_uri=os.environ.get("PROMPT_GCS_URI"),
        ),
    )
