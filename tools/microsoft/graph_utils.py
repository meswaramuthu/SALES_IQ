"""Shared Microsoft Graph API helpers — token acquisition, session, GET/POST/PATCH/PUT/DELETE.

Used by onedrive_tool.py and outlook_tool.py. SharePoint has its own copy
intentionally to avoid a dependency on this module while it is already deployed.
"""
from __future__ import annotations

import threading
from typing import Any

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_msal_apps: dict[str, Any] = {}
_msal_lock = threading.Lock()


def get_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    key = f"{tenant_id}:{client_id}"
    with _msal_lock:
        if key not in _msal_apps:
            import msal
            _msal_apps[key] = msal.ConfidentialClientApplication(
                client_id=client_id,
                authority=f"https://login.microsoftonline.com/{tenant_id}",
                client_credential=client_secret,
            )
    app = _msal_apps[key]
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(
            "MSAL token acquisition failed: "
            + (result.get("error_description") or result.get("error") or str(result))
        )
    return result["access_token"]


def graph_session(token: str):
    import requests
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
    return sess


def graph_get(sess, path: str, params: dict | None = None) -> dict:
    resp = sess.get(f"{_GRAPH_BASE}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def graph_post(sess, path: str, json_body: dict | None = None, params: dict | None = None) -> dict:
    resp = sess.post(
        f"{_GRAPH_BASE}{path}",
        json=json_body,
        params=params,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def graph_patch(sess, path: str, json_body: dict | None = None) -> dict:
    resp = sess.patch(
        f"{_GRAPH_BASE}{path}",
        json=json_body,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def graph_put_bytes(sess, path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
    resp = sess.put(
        f"{_GRAPH_BASE}{path}",
        data=data,
        headers={"Content-Type": content_type},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def graph_delete(sess, path: str) -> bool:
    resp = sess.delete(f"{_GRAPH_BASE}{path}", timeout=30)
    resp.raise_for_status()
    return True
