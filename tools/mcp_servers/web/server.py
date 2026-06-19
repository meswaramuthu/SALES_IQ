"""Web Scraper MCP — scrape any URL and ingest into Gemini Enterprise data store."""
from __future__ import annotations

import hashlib
import json
import logging
import os
_PORT = int(os.environ.get("PORT", 8080))

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("stratova-web-scraper", host="0.0.0.0", port=_PORT)

PROJECT_ID    = os.environ.get("GEMINI_PROJECT_ID", "ninth-archway-496404-s2")
DATA_STORE_ID = os.environ.get("WEB_SCRAPER_DS_ID", "")
LOCATION      = os.environ.get("GEMINI_LOCATION", "global")
_BASE = "https://discoveryengine.googleapis.com/v1"


def _token() -> str:
    import google.auth, google.auth.transport.requests
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _ingest_to_discovery_engine(doc_id: str, title: str, url: str, text: str) -> None:
    import requests as req
    if not DATA_STORE_ID:
        logger.warning("WEB_SCRAPER_DS_ID not set — skipping DS ingest")
        return
    endpoint = (
        f"{_BASE}/projects/{PROJECT_ID}/locations/{LOCATION}"
        f"/collections/default_collection/dataStores/{DATA_STORE_ID}"
        f"/branches/default_branch/documents/{doc_id}"
    )
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": PROJECT_ID,
    }
    body = {
        "id": doc_id,
        "jsonData": json.dumps({"title": title, "url": url, "content": text}),
    }
    resp = req.request("PATCH", endpoint, headers=headers, json=body,
                        params={"allowMissing": "true"}, timeout=30)
    resp.raise_for_status()


@mcp.tool()
def scrape_and_ingest_url(url: str) -> dict:
    """Fetch any public URL, extract clean text, ingest into Gemini Enterprise
    Website data store. After ingestion content is searchable via
    search_gemini_connectors(). Accepts ANY URL — no domain restrictions.

    Args:
        url: Full URL to scrape e.g. "https://laabu.com/marketing-package"
    """
    import requests as req
    from bs4 import BeautifulSoup

    try:
        html = req.get(url, timeout=15, headers={"User-Agent": "Stratova-Bot/1.0"}).text
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else url
        text  = soup.get_text(separator=" ", strip=True)[:50_000]
        doc_id = hashlib.md5(url.encode()).hexdigest()

        _ingest_to_discovery_engine(doc_id, title, url, text)

        return {
            "status": "indexed",
            "document_id": doc_id,
            "url": url,
            "title": title,
            "chars_indexed": len(text),
        }
    except Exception as exc:
        logger.error("scrape_and_ingest_url %s error: %s", url, exc)
        return {"status": "error", "url": url, "error": str(exc)}


@mcp.tool()
def get_indexed_pages(query: str = "") -> dict:
    """List pages currently indexed in the website data store.

    Args:
        query: Optional filter — returns pages whose title/URL contains this string.
    """
    import requests as req

    if not DATA_STORE_ID:
        return {"pages": [], "error": "WEB_SCRAPER_DS_ID not configured"}
    try:
        endpoint = (
            f"{_BASE}/projects/{PROJECT_ID}/locations/{LOCATION}"
            f"/collections/default_collection/dataStores/{DATA_STORE_ID}"
            f"/branches/default_branch/documents"
        )
        headers = {
            "Authorization": f"Bearer {_token()}",
            "X-Goog-User-Project": PROJECT_ID,
        }
        resp = req.get(endpoint, headers=headers, params={"pageSize": 50}, timeout=20)
        resp.raise_for_status()
        docs = resp.json().get("documents", [])
        pages = []
        for d in docs:
            jd = json.loads(d.get("jsonData", "{}"))
            if not query or query.lower() in (jd.get("title","") + jd.get("url","")).lower():
                pages.append({"title": jd.get("title",""), "url": jd.get("url",""), "id": d.get("id","")})
        return {"pages": pages, "count": len(pages)}
    except Exception as exc:
        logger.error("get_indexed_pages error: %s", exc)
        return {"pages": [], "error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
