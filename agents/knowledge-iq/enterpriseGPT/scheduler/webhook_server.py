"""Cloud Run Service — webhook receiver for live document-change events.

Routes:
  GET  /health                → liveness probe (used by Cloud Run health checks)
  POST /webhook/sharepoint    → Microsoft Graph change notifications
  POST /webhook/github        → GitHub push events

On a valid notification each route immediately returns 202 Accepted, then runs
the relevant connector's sync in a FastAPI BackgroundTask. The background task
loads the latest state, runs the delta sync, and saves state back to GCS.

For high-throughput environments replace BackgroundTasks with a Cloud Tasks or
Pub/Sub enqueue so the HTTP response returns before the (potentially long) sync.

Startup:
  python -m sync.webhook_server
  (or set CMD in Dockerfile.webhook)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response

from scheduler import config as cfg
from scheduler.state import StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App state — populated during lifespan startup
# ---------------------------------------------------------------------------
_connectors: dict = {}
_store: StateStore | None = None
_corpus: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _connectors, _store, _corpus

    from config import get_config
    from scheduler.job import build_connectors

    agent_cfg = get_config()
    built = build_connectors(agent_cfg)
    _connectors = {c.NAME: c for c in built}
    _store = StateStore(cfg.get_state_gcs_uri())
    _corpus = cfg.get_corpus()

    logger.info(
        "Webhook server ready — connectors: %s, corpus: %s",
        list(_connectors.keys()),
        _corpus,
    )
    yield


app = FastAPI(
    title="Knowledge IQ — Sync Webhook Service",
    description="Receives push notifications from SharePoint and GitHub and triggers RAG delta sync.",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "connectors": list(_connectors.keys()),
        "corpus_set": bool(_corpus),
    }


# ---------------------------------------------------------------------------
# SharePoint (Microsoft Graph change notifications)
# ---------------------------------------------------------------------------

@app.post("/webhook/sharepoint")
async def sharepoint_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    validationToken: str = Query(default=""),  # noqa: N803 — Graph uses camelCase param
):
    """Handle Graph subscription validation and change notifications.

    Graph first sends a POST/GET with ?validationToken=... to verify the endpoint.
    We must echo the token back as text/plain within 10 seconds.
    Subsequent notifications arrive as JSON POST bodies.
    """
    connector = _connectors.get("sharepoint")
    if not connector:
        raise HTTPException(status_code=503, detail="SharePoint connector not configured")

    body = await request.body()
    headers = dict(request.headers)
    query_params = dict(request.query_params)

    is_valid, echo_body = connector.validate_webhook(headers, body, query_params)
    if not is_valid:
        raise HTTPException(status_code=403, detail="Webhook validation failed")

    # Subscription validation handshake — must return the token as text/plain
    if echo_body:
        return Response(content=echo_body, media_type="text/plain", status_code=200)

    # Genuine notification — trigger async sync
    drive_ids = connector.get_changed_drive_ids(body)
    logger.info("SharePoint notification: drives changed = %s", drive_ids)
    background_tasks.add_task(_run_connector_sync, "sharepoint")
    return Response(status_code=202)


# ---------------------------------------------------------------------------
# GitHub push events
# ---------------------------------------------------------------------------

@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    connector = _connectors.get("github")
    if not connector:
        raise HTTPException(status_code=503, detail="GitHub connector not configured")

    body = await request.body()
    headers = dict(request.headers)

    is_valid, _ = connector.validate_webhook(headers, body, {})
    if not is_valid:
        raise HTTPException(status_code=403, detail="Webhook signature invalid")

    event = headers.get("x-github-event", "")
    if event == "ping":
        return Response(status_code=200)  # webhook registration confirmation
    if event != "push":
        return Response(status_code=204)  # ignore other event types

    repo_name = connector.get_push_event_repo(body)
    head_sha = connector.get_push_event_head_sha(body)
    logger.info("GitHub push: %s @ %s", repo_name, head_sha[:8] if head_sha else "?")
    background_tasks.add_task(_run_connector_sync, "github")
    return Response(status_code=202)


# ---------------------------------------------------------------------------
# Shared background sync helper
# ---------------------------------------------------------------------------

def _run_connector_sync(connector_name: str) -> None:
    """Load state, run one connector's delta sync, save state. Called in background."""
    connector = _connectors.get(connector_name)
    if connector is None or _store is None or not _corpus:
        logger.error(
            "Cannot run sync for '%s' — connector=%s store=%s corpus=%s",
            connector_name, connector is not None, _store is not None, bool(_corpus),
        )
        return

    state = _store.load()
    cs = state.connector(connector_name)
    try:
        result = connector.sync(cs, _corpus)
        logger.info("Webhook-triggered sync: %s", result)
        if result.errors:
            for err in result.errors:
                logger.warning("  • %s", err)
    except Exception as exc:
        logger.error(
            "Webhook-triggered sync for '%s' failed: %s", connector_name, exc, exc_info=True
        )
    finally:
        _store.save(state)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=cfg.get_webhook_port(), log_level="info")
