"""Cloud Run Job entry point — scheduled full / delta sync.

Reads TOOLS_CONFIG_GCS_URI (same as the Knowledge IQ agent) for credentials,
loads sync-specific settings from env vars (see sync/config.py), then runs
every enabled connector in sequence and saves the updated state to GCS.

Exit codes:
  0 — all connectors completed without errors
  1 — at least one connector had errors or configuration is missing

Typical invocation (set by Cloud Run Job CMD):
  python -m sync.job
"""
from __future__ import annotations

import logging
import sys

from scheduler import config as cfg
from scheduler.state import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connector factory
# ---------------------------------------------------------------------------

def build_connectors(agent_cfg) -> list:
    """Instantiate connectors for every enabled tool that has a corresponding connector."""
    connectors = []

    # ── SharePoint ────────────────────────────────────────────────────────────
    sp_cfg = agent_cfg.tools.get("sharepoint")
    if sp_cfg and sp_cfg.enabled:
        sites = cfg.get_sharepoint_sites()
        if not sites and sp_cfg.config.get("site_url"):
            sites = [sp_cfg.config["site_url"]]

        if sites:
            from scheduler.connectors.sharepoint import SharePointConnector

            webhook_base = sp_cfg.config.get("webhook_base_url", "")
            connectors.append(
                SharePointConnector(
                    tenant_id=sp_cfg.config.get("tenant_id", ""),
                    client_id=sp_cfg.config.get("client_id", ""),
                    client_secret=sp_cfg.config.get("client_secret", ""),
                    site_urls=sites,
                    webhook_base_url=webhook_base,
                    client_state=cfg.get_sharepoint_client_state(),
                )
            )
            logger.info("SharePoint connector: %d site(s)", len(sites))
        else:
            logger.warning("SharePoint is enabled but no site URLs configured — skipping")

    # ── GitHub ────────────────────────────────────────────────────────────────
    gh_cfg = agent_cfg.tools.get("github")
    if gh_cfg and gh_cfg.enabled:
        repos = cfg.get_github_repos()
        if not repos:
            repos = _discover_github_repos(
                gh_cfg.config.get("token", ""),
                gh_cfg.config.get("default_org", ""),
            )

        if repos:
            from scheduler.connectors.github import GitHubConnector

            connectors.append(
                GitHubConnector(
                    token=gh_cfg.config.get("token", ""),
                    repos=repos,
                    file_exts=cfg.get_github_file_exts(),
                    webhook_secret=cfg.get_github_webhook_secret(),
                )
            )
            logger.info("GitHub connector: %d repo(s)", len(repos))
        else:
            logger.warning("GitHub is enabled but no repos found — skipping")

    return connectors


def _discover_github_repos(token: str, org: str) -> list[str]:
    if not token or not org:
        return []
    try:
        from github import Auth, Github

        gh = Github(auth=Auth.Token(token))
        repos = [r.full_name for r in gh.get_organization(org).get_repos(type="all")]
        gh.close()
        logger.info("Discovered %d repos in org '%s'", len(repos), org)
        return repos
    except Exception as exc:
        logger.warning("GitHub repo discovery failed for org '%s': %s", org, exc)
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    corpus = cfg.get_corpus()
    state_uri = cfg.get_state_gcs_uri()

    if not corpus:
        logger.error("RAG_CORPUS env var is not set — cannot sync")
        return 1
    if not state_uri:
        logger.error("SYNC_STATE_GCS_URI env var is not set — cannot persist state")
        return 1

    from config import get_config

    agent_cfg = get_config()
    connectors = build_connectors(agent_cfg)

    if not connectors:
        logger.warning("No connectors are enabled — nothing to sync")
        return 0

    store = StateStore(state_uri)
    state = store.load()

    any_error = False
    for connector in connectors:
        cs = state.connector(connector.NAME)
        try:
            result = connector.sync(cs, corpus)
            logger.info("%s", result)
            if result.errors:
                for err in result.errors:
                    logger.warning("  • %s", err)
                any_error = True
        except Exception as exc:
            logger.error("Connector '%s' raised an unhandled exception: %s", connector.NAME, exc, exc_info=True)
            any_error = True

    # Always persist state even on partial errors so next run continues from where we left off
    store.save(state)

    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
