"""RAG tools — thin wrapper around stratova_shared.rag_tool.

All implementation lives in agents/shared/stratova_shared/rag_tool.py.
This module just wires the shared factory to the Knowledge IQ config getter.
"""
from __future__ import annotations

from typing import Callable

from config import get_config
from stratova_shared.rag_tool import build_rag_tools


def get_tools() -> list[Callable]:
    return build_rag_tools(config_getter=get_config)
