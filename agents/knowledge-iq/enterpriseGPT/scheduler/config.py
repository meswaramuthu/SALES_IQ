"""Sync service configuration — loaded from environment variables.

The sync service shares tool credentials (SharePoint, GitHub) with the Knowledge IQ
agent by reading the same TOOLS_CONFIG_GCS_URI. Sync-specific settings are
controlled by the env vars below so each deployment target (job vs webhook service)
can have its own configuration without touching the shared agent config.

Required:
  TOOLS_CONFIG_GCS_URI   Same GCS URI as the agent (loads SharePoint / GitHub creds)
  RAG_CORPUS             Vertex AI RAG corpus resource name
  SYNC_STATE_GCS_URI     GCS URI for persisting sync state
                         e.g. gs://my-bucket/knowledge-iq/sync-state.json

SharePoint:
  SYNC_SHAREPOINT_SITES  Comma-separated SharePoint site URLs to crawl.
                         Defaults to the site_url set in tools_config.json.
  SYNC_SP_CLIENT_STATE   Secret string echoed in Graph webhook payloads for validation.
                         Set the same value when registering Graph subscriptions.
                         Default: "stratova-sync-v1"

GitHub:
  SYNC_GITHUB_REPOS      Comma-separated "owner/repo" slugs to sync.
                         If blank, all repos in the configured org are auto-discovered.
  SYNC_GITHUB_FILE_EXTS  Comma-separated file extensions to index (default covers common
                         doc + code formats — see DEFAULT_GITHUB_EXTS below).
  SYNC_GITHUB_WEBHOOK_SECRET  HMAC secret for verifying GitHub push events.

Webhook server:
  SYNC_WEBHOOK_PORT      HTTP port for the webhook receiver (default: 8080)
"""
from __future__ import annotations

import os

DEFAULT_GITHUB_EXTS = (
    ".md,.txt,.rst,.html,.htm,.pdf,.docx,"
    ".py,.ts,.js,.go,.yaml,.yml,.json,.sh,.sql"
)


def get_corpus() -> str:
    return os.environ.get("RAG_CORPUS", "")


def get_state_gcs_uri() -> str:
    return os.environ.get("SYNC_STATE_GCS_URI", "")


def get_sharepoint_sites() -> list[str]:
    raw = os.environ.get("SYNC_SHAREPOINT_SITES", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def get_sharepoint_client_state() -> str:
    return os.environ.get("SYNC_SP_CLIENT_STATE", "stratova-sync-v1")


def get_github_repos() -> list[str]:
    raw = os.environ.get("SYNC_GITHUB_REPOS", "")
    return [r.strip() for r in raw.split(",") if r.strip()]


def get_github_file_exts() -> frozenset[str]:
    raw = os.environ.get("SYNC_GITHUB_FILE_EXTS", DEFAULT_GITHUB_EXTS)
    return frozenset(e.strip() for e in raw.split(",") if e.strip())


def get_github_webhook_secret() -> str:
    return os.environ.get("SYNC_GITHUB_WEBHOOK_SECRET", "")


def get_webhook_port() -> int:
    return int(os.environ.get("SYNC_WEBHOOK_PORT", "8080"))
