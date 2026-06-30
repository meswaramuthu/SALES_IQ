"""Shared Zoho OAuth2 token refresh logic.

All four Zoho tools (CRM, Desk, Books, People) call get_zoho_access_token()
instead of reading a raw access_token from config.  A module-level cache keyed
by client_id means the token endpoint is only hit once per hour across all tools,
not once per call.

Config keys consumed (read from each tool's cfg dict):
  client_id     : Zoho OAuth2 client ID
  client_secret : Zoho OAuth2 client secret
  refresh_token : Zoho OAuth2 refresh token (permanent until revoked)
  accounts_url  : (optional) Zoho accounts domain for the token endpoint
                    US  → https://accounts.zoho.com   (default)
                    EU  → https://accounts.zoho.eu
                    IN  → https://accounts.zoho.in
                    AU  → https://accounts.zoho.com.au

Fallback:
  If client_id / client_secret / refresh_token are absent, the function falls
  back to cfg['access_token'] so existing manual tokens work without changes
  during local development and testing.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# (access_token, expires_at_unix_timestamp) keyed by client_id
_cache: Dict[str, Tuple[str, float]] = {}

# Refresh 60 s before actual expiry so no call ever sees an expired token.
_EXPIRY_BUFFER_SECS = 60


def get_zoho_access_token(cfg: dict) -> str:
    """Return a valid Zoho access token, auto-refreshing when it expires.

    The token is cached in memory per client_id.  On the first call (or after
    expiry) it performs a refresh-token exchange with the Zoho accounts server
    and caches the new token for the remainder of its lifetime.

    Args:
        cfg: The tool's config dict from tools_config.json.

    Returns:
        A valid bearer token string to put in Authorization headers.

    Raises:
        RuntimeError: If the token endpoint returns an error response.
        requests.HTTPError: If the HTTP request to Zoho accounts fails.
    """
    client_id = cfg.get("client_id", "")
    client_secret = cfg.get("client_secret", "")
    refresh_token = cfg.get("refresh_token", "")

    # Fallback for local dev: static access_token, expires in 1 hour.
    if not (client_id and client_secret and refresh_token):
        logger.warning(
            "Zoho refresh credentials not configured; falling back to static "
            "access_token (expires in 1 hour — not suitable for production)."
        )
        return cfg.get("access_token", "")

    # Return cached token if it still has more than _EXPIRY_BUFFER_SECS left.
    cached = _cache.get(client_id)
    if cached:
        token, expires_at = cached
        if time.time() < expires_at - _EXPIRY_BUFFER_SECS:
            return token

    return _refresh(client_id, client_secret, refresh_token, cfg)


def _refresh(client_id: str, client_secret: str, refresh_token: str, cfg: dict) -> str:
    """Exchange the refresh token for a new access token and update the cache."""
    import requests

    accounts_url = cfg.get("accounts_url", "https://accounts.zoho.com").rstrip("/")
    endpoint = f"{accounts_url}/oauth/v2/token"

    resp = requests.post(
        endpoint,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if "access_token" not in data:
        raise RuntimeError(
            f"Zoho token refresh failed (no access_token in response): {data}"
        )

    access_token: str = data["access_token"]
    expires_in: int = int(data.get("expires_in", 3600))
    _cache[client_id] = (access_token, time.time() + expires_in)

    logger.info(
        "Zoho access token refreshed for client_id=%.8s... (expires in %ds)",
        client_id,
        expires_in,
    )
    return access_token


def clear_cache(client_id: str | None = None) -> None:
    """Evict one or all cached tokens (useful in tests)."""
    if client_id is None:
        _cache.clear()
    else:
        _cache.pop(client_id, None)
