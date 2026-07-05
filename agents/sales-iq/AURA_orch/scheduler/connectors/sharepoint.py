"""SharePoint sync connector — Microsoft Graph delta API.

Delta query flow (per drive / document library):
  First run  : GET /drives/{id}/root/delta                → full crawl + deltaLink stored
  Later runs : GET {stored_deltaLink}                      → only changed items since last run

Each delta response item is either:
  - A file   → download and upsert into RAG (skip if etag unchanged)
  - A folder → skip
  - Deleted  → remove the corresponding RAG file and state entry

Webhook support:
  The webhook route echoes back the validationToken on subscription creation, and
  validates subsequent notifications by checking the clientState field against the
  configured SYNC_SP_CLIENT_STATE secret. On a valid notification the webhook server
  triggers an immediate delta sync for the affected drive.

  Graph subscription limits:
    - Max lifetime for driveItem subscriptions: 4320 minutes (~3 days)
    - The cron job renews subscriptions on every run (idempotent upsert)
    - Subscription IDs are stored in ConnectorState.drive_delta_tokens under the
      key "sub:{drive_id}" so they share the same dict without clashing with delta
      link entries keyed by drive_id directly.

Required env vars (via tools_config.json sharepoint section):
  tenant_id, client_id, client_secret — Azure AD app registration (Application permissions:
  Sites.Read.All, Files.Read.All)
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from scheduler.connectors.base import BaseConnector, SyncResult
from scheduler.ingestion import RAG_SUPPORTED_EXTS, delete_from_rag, upload_to_rag
from scheduler.state import ConnectorState, FileRecord

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_MAX_FILE_BYTES = 50 * 1024 * 1024

_msal_apps: dict[str, Any] = {}
_msal_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Auth helpers (mirrors sharepoint_tool.py — MSAL app cache per tenant/client)
# ---------------------------------------------------------------------------

def _get_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    key = f"{tenant_id}:{client_id}"
    with _msal_lock:
        if key not in _msal_apps:
            import msal
            _msal_apps[key] = msal.ConfidentialClientApplication(
                client_id=client_id,
                authority=f"https://login.microsoftonline.com/{tenant_id}",
                client_credential=client_secret,
            )
    result = _msal_apps[key].acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        raise RuntimeError(
            "MSAL auth failed: " + (result.get("error_description") or str(result))
        )
    return result["access_token"]


def _session(token: str) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
    return sess


def _graph_get(sess: requests.Session, path: str, params: Optional[dict] = None) -> dict:
    resp = sess.get(f"{_GRAPH_BASE}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _graph_post(sess: requests.Session, path: str, body: dict) -> dict:
    resp = sess.post(f"{_GRAPH_BASE}{path}", json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _resolve_site_id(sess: requests.Session, site_url: str) -> str:
    parsed = urlparse(site_url)
    data = _graph_get(sess, f"/sites/{parsed.netloc}:{parsed.path}")
    return data["id"]


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class SharePointConnector(BaseConnector):
    NAME = "sharepoint"

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        site_urls: list[str],
        webhook_base_url: str = "",
        client_state: str = "stratova-sync-v1",
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._site_urls = site_urls
        self._webhook_base_url = webhook_base_url  # needed only for subscription registration
        self._client_state = client_state

    # ------------------------------------------------------------------
    # Public sync entry point
    # ------------------------------------------------------------------

    def sync(self, cs: ConnectorState, corpus: str) -> SyncResult:
        result = SyncResult(connector=self.NAME)
        try:
            token = _get_token(self._tenant_id, self._client_id, self._client_secret)
        except Exception as exc:
            result.errors.append(f"auth: {exc}")
            return result

        sess = _session(token)

        for site_url in self._site_urls:
            try:
                site_id = _resolve_site_id(sess, site_url)
                drives_data = _graph_get(sess, f"/sites/{site_id}/drives")
                site_name = site_url.rstrip("/").split("/")[-1]
                for drive in drives_data.get("value", []):
                    self._sync_drive(sess, drive["id"], drive.get("name", ""), site_name, cs, corpus, result)
            except Exception as exc:
                msg = f"site {site_url}: {exc}"
                logger.error("SharePoint — %s", msg)
                result.errors.append(msg)

        # Renew Graph subscriptions so the webhook keeps receiving notifications
        if self._webhook_base_url:
            self._renew_subscriptions(sess, cs)

        cs.last_sync_utc = datetime.now(timezone.utc).isoformat()
        return result

    # ------------------------------------------------------------------
    # Drive-level delta sync
    # ------------------------------------------------------------------

    def _sync_drive(
        self,
        sess: requests.Session,
        drive_id: str,
        drive_name: str,
        site_name: str,
        cs: ConnectorState,
        corpus: str,
        result: SyncResult,
    ) -> None:
        stored_link = cs.drive_delta_tokens.get(drive_id)
        url = stored_link if stored_link else f"{_GRAPH_BASE}/drives/{drive_id}/root/delta"

        logger.info(
            "SharePoint: syncing drive '%s' (%s) — %s",
            drive_name,
            drive_id,
            "incremental" if stored_link else "full crawl",
        )

        while url:
            try:
                resp = sess.get(url, timeout=60)
                # 410 Gone = delta token expired → fall back to full resync
                if resp.status_code == 410:
                    logger.warning(
                        "Delta token expired for drive %s — resetting to full crawl", drive_id
                    )
                    cs.drive_delta_tokens.pop(drive_id, None)
                    cs.files = {k: v for k, v in cs.files.items()
                                if not k.startswith(f"{drive_id}/")}
                    self._sync_drive(sess, drive_id, drive_name, site_name, cs, corpus, result)
                    return
                resp.raise_for_status()
                data = resp.json()
            except requests.HTTPError as exc:
                result.errors.append(f"delta_query drive={drive_id}: {exc}")
                return

            for item in data.get("value", []):
                self._process_item(sess, drive_id, item, site_name, cs, corpus, result)

            next_link = data.get("@odata.nextLink")
            delta_link = data.get("@odata.deltaLink")

            if delta_link:
                cs.drive_delta_tokens[drive_id] = delta_link
                url = None
            elif next_link:
                url = next_link
            else:
                url = None

    # ------------------------------------------------------------------
    # Per-item processing
    # ------------------------------------------------------------------

    def _process_item(
        self,
        sess: requests.Session,
        drive_id: str,
        item: dict,
        site_name: str,
        cs: ConnectorState,
        corpus: str,
        result: SyncResult,
    ) -> None:
        item_id = item.get("id", "")
        state_key = f"{drive_id}/{item_id}"

        # Deleted item
        if "deleted" in item:
            record = cs.files.get(state_key)
            if record and record.rag_file_name:
                if delete_from_rag(record.rag_file_name):
                    del cs.files[state_key]
                    result.deleted += 1
            return

        # Folders don't have content
        if "folder" in item:
            return

        name = item.get("name", "")
        _, ext = os.path.splitext(name)
        if ext.lower() not in RAG_SUPPORTED_EXTS:
            result.skipped += 1
            return

        if item.get("size", 0) > _MAX_FILE_BYTES:
            logger.warning("Skipping large file %s (%d bytes)", name, item.get("size"))
            result.skipped += 1
            return

        last_modified = item.get("lastModifiedDateTime", "")
        etag = item.get("eTag", "")
        existing = cs.files.get(state_key)

        # Skip if nothing changed (same etag, already in RAG)
        if existing and existing.etag == etag and existing.rag_file_name:
            return

        # Resolve download URL
        download_url = item.get("@microsoft.graph.downloadUrl", "")
        if not download_url:
            try:
                meta = _graph_get(sess, f"/drives/{drive_id}/items/{item_id}")
                download_url = meta.get("@microsoft.graph.downloadUrl", "")
            except Exception as exc:
                result.errors.append(f"download_url {name}: {exc}")
                return

        try:
            file_resp = requests.get(download_url, timeout=120)
            file_resp.raise_for_status()
            content = file_resp.content
        except Exception as exc:
            result.errors.append(f"download {name}: {exc}")
            return

        # Remove stale RAG entry before uploading updated version
        if existing and existing.rag_file_name:
            delete_from_rag(existing.rag_file_name)

        web_url = item.get("webUrl", "")
        _, ext = os.path.splitext(name)
        rag_name = upload_to_rag(
            content=content,
            filename=name,
            display_name=f"sharepoint/{name}",
            corpus_name=corpus,
            description=f"SharePoint: {web_url}",
            source_metadata={
                "source": "sharepoint",
                "site": site_name,
                "file_ext": ext.lower().lstrip("."),
                "last_modified": last_modified[:10] if last_modified else "",
            },
        )
        if rag_name:
            cs.files[state_key] = FileRecord(
                name=name,
                last_modified=last_modified,
                rag_file_name=rag_name,
                etag=etag,
            )
            result.upserted += 1
        else:
            result.errors.append(f"rag_upload_failed: {name}")

    # ------------------------------------------------------------------
    # Graph subscription management (for webhook fast-path)
    # ------------------------------------------------------------------

    def _renew_subscriptions(self, sess: requests.Session, cs: ConnectorState) -> None:
        """Create or renew a Graph change-notification subscription for each drive."""
        from datetime import timedelta

        webhook_url = f"{self._webhook_base_url.rstrip('/')}/webhook/sharepoint"
        # Subscriptions expire in max 4320 minutes; renew to a fresh 4319-minute window
        expiry = (
            datetime.now(timezone.utc) + timedelta(minutes=4319)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        for site_url in self._site_urls:
            try:
                site_id = _resolve_site_id(sess, site_url)
                drives = _graph_get(sess, f"/sites/{site_id}/drives").get("value", [])
                for drive in drives:
                    drive_id = drive["id"]
                    sub_key = f"sub:{drive_id}"
                    existing_sub_id = cs.drive_delta_tokens.get(sub_key, "")

                    body = {
                        "changeType": "updated,deleted,created",
                        "notificationUrl": webhook_url,
                        "resource": f"/drives/{drive_id}/root",
                        "expirationDateTime": expiry,
                        "clientState": self._client_state,
                    }

                    try:
                        if existing_sub_id:
                            # PATCH to extend expiry
                            resp = sess.patch(
                                f"{_GRAPH_BASE}/subscriptions/{existing_sub_id}",
                                json={"expirationDateTime": expiry},
                                timeout=30,
                            )
                            if resp.status_code == 404:
                                raise requests.HTTPError("not found")
                            resp.raise_for_status()
                            logger.info("Renewed Graph subscription %s (drive %s)", existing_sub_id, drive_id)
                        else:
                            sub_resp = _graph_post(sess, "/subscriptions", body)
                            cs.drive_delta_tokens[sub_key] = sub_resp["id"]
                            logger.info("Created Graph subscription %s (drive %s)", sub_resp["id"], drive_id)
                    except Exception as exc:
                        # If renewal failed, clear stored ID and try creating fresh
                        if existing_sub_id:
                            cs.drive_delta_tokens.pop(sub_key, None)
                            try:
                                sub_resp = _graph_post(sess, "/subscriptions", body)
                                cs.drive_delta_tokens[sub_key] = sub_resp["id"]
                                logger.info("Re-created Graph subscription (drive %s)", drive_id)
                            except Exception as inner_exc:
                                logger.warning("Could not create subscription for drive %s: %s", drive_id, inner_exc)
                        else:
                            logger.warning("Could not create subscription for drive %s: %s", drive_id, exc)
            except Exception as exc:
                logger.warning("Subscription renewal failed for %s: %s", site_url, exc)

    # ------------------------------------------------------------------
    # Webhook validation helpers
    # ------------------------------------------------------------------

    def validate_webhook(
        self, headers: dict, body: bytes, query_params: dict
    ) -> tuple[bool, str]:
        # Graph subscription validation: echo back validationToken
        validation_token = query_params.get("validationToken", "")
        if validation_token:
            return True, validation_token

        # Notification: verify every notification's clientState
        try:
            data = json.loads(body or b"{}")
            for notification in data.get("value", []):
                if notification.get("clientState", "") != self._client_state:
                    logger.warning(
                        "SharePoint webhook: invalid clientState '%s'",
                        notification.get("clientState"),
                    )
                    return False, ""
        except Exception:
            return False, ""
        return True, ""

    def get_changed_drive_ids(self, body: bytes) -> list[str]:
        """Return drive IDs affected by a Graph change notification payload."""
        drive_ids: list[str] = []
        try:
            data = json.loads(body or b"{}")
            for notification in data.get("value", []):
                # resource: "drives/{drive_id}/root" or similar
                parts = notification.get("resource", "").split("/")
                if len(parts) >= 2 and parts[0] == "drives":
                    drive_ids.append(parts[1])
        except Exception:
            pass
        return list(dict.fromkeys(drive_ids))  # deduplicate, preserve order
