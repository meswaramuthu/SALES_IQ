"""Gemini Enterprise DS MCP — search all data stores + trigger Actions + Apollo.io direct."""
from __future__ import annotations

import logging
import os
_PORT = int(os.environ.get("PORT", 8080))

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("stratova-gemini-ds", host="0.0.0.0", port=_PORT)

PROJECT_ID = os.environ.get("GEMINI_PROJECT_ID", "ninth-archway-496404-s2")
ENGINE_ID  = os.environ.get("GEMINI_ENGINE_ID", "stratova-gemini_1779267526762")
LOCATION   = os.environ.get("GEMINI_LOCATION", "global")

# Apollo.io direct REST (fallback when Gemini DS confidence is low or Action not yet configured)
_APOLLO_BASE = "https://api.apollo.io/v1"

_BASE = "https://discoveryengine.googleapis.com/v1"


def _token() -> str:
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


@mcp.tool()
def search_gemini_connectors(query: str, max_results: int = 10) -> dict:
    """Search ALL Gemini Enterprise data stores with a single query.

    Searches HubSpot DS, Apollo DS, SharePoint DS, Website DS, and Drive DS
    simultaneously. No code change needed when new data stores are added.

    Args:
        query: Natural language or keyword search query.
        max_results: Max results to return (default 10, max 25).
    """
    import requests as req

    max_results = min(max_results, 25)
    url = (
        f"{_BASE}/projects/{PROJECT_ID}/locations/{LOCATION}"
        f"/collections/default_collection/engines/{ENGINE_ID}"
        f"/servingConfigs/default_search:search"
    )
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": PROJECT_ID,
    }
    body = {
        "query": query,
        "pageSize": max_results,
        "queryExpansionSpec": {"condition": "AUTO"},
        "spellCorrectionSpec": {"mode": "AUTO"},
        "contentSearchSpec": {
            "snippetSpec": {"returnSnippet": True, "maxSnippetCount": 3},
            "extractiveContentSpec": {"maxExtractiveAnswerCount": 2},
        },
    }
    try:
        resp = req.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        raw_results = resp.json().get("results", [])
        results = []
        for r in raw_results:
            doc = r.get("document", {})
            derived = doc.get("derivedStructData", {})
            struct  = doc.get("structData", {})
            title   = derived.get("title") or struct.get("title") or doc.get("id", "")
            link    = derived.get("link") or derived.get("uri") or ""
            source  = derived.get("datasource_type") or "connector"
            snippets = [s.get("snippet","") for s in derived.get("snippets",[]) if s.get("snippet")]
            answers  = [a.get("content","") for a in derived.get("extractive_answers",[]) if a.get("content")]
            results.append({
                "title": title, "source": source, "link": link,
                "snippet": " ".join(snippets[:2]),
                "content": " ".join(answers[:2]),
            })
        return {"results": results, "count": len(results), "query": query}
    except Exception as exc:
        logger.error("search_gemini_connectors error: %s", exc)
        return {"results": [], "count": 0, "error": str(exc)}


@mcp.tool()
def trigger_gemini_action(action_name: str, parameters: dict) -> dict:
    """Trigger a Gemini Enterprise Action (write operation).

    Actions are OpenAPI tools configured in the Gemini Enterprise console.
    API keys for HubSpot and Apollo are stored in the Action config — not here.

    Available actions:
      create_hubspot_lead(email, name, company, pain_point)
      advance_hubspot_stage(deal_id, stage_name)
      add_hubspot_note(deal_id, note_text)
      set_hubspot_property(deal_id, key, value)
      apollo_enrich_company(domain)

    Args:
        action_name: Name of the configured Gemini Enterprise Action.
        parameters:  Dict of parameters matching the action's OpenAPI spec.
    """
    import requests as req

    url = (
        f"{_BASE}/projects/{PROJECT_ID}/locations/{LOCATION}"
        f"/collections/default_collection/engines/{ENGINE_ID}"
        f"/actions/{action_name}:execute"
    )
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": PROJECT_ID,
    }
    try:
        resp = req.post(url, headers=headers, json={"parameters": parameters}, timeout=30)
        resp.raise_for_status()
        return {"status": "ok", "action": action_name, "result": resp.json()}
    except Exception as exc:
        logger.error("trigger_gemini_action %s error: %s", action_name, exc)
        return {"status": "error", "action": action_name, "error": str(exc)}


@mcp.tool()
def enrich_company_apollo(domain: str) -> dict:
    """Enrich a company directly from Apollo.io REST API by domain.

    Use this when:
    - search_gemini_connectors() returns low-confidence results (< 0.70)
    - The Gemini Enterprise Action 'apollo_enrich_company' is not yet configured
    - You need fresh real-time data (not cached DS data)

    Requires APOLLO_API_KEY env var in this MCP server's Cloud Run config.
    Key is stored ONLY here — not in any agent package.

    Args:
        domain: Company website domain, e.g. "vantageclinical.com"

    Returns:
        dict with: company, domain, headcount, industry, revenue, website,
                   description, enrichment_source. headcount is the routing
                   signal: < 100 = SME self-serve, >= 100 = Enterprise.
    """
    import requests as req

    api_key = os.environ.get("APOLLO_API_KEY", "")
    if not api_key:
        logger.warning("APOLLO_API_KEY not set — Apollo.io direct enrichment unavailable")
        return {
            "status": "unavailable",
            "reason": "APOLLO_API_KEY not configured in MCP server",
            "domain": domain,
        }

    try:
        resp = req.post(
            f"{_APOLLO_BASE}/organizations/enrich",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json", "Cache-Control": "no-cache"},
            json={"domain": domain},
            timeout=15,
        )
        resp.raise_for_status()
        org = resp.json().get("organization") or {}
        return {
            "status": "ok",
            "enrichment_source": "apollo_direct",
            "company": org.get("name", ""),
            "domain": domain,
            "headcount": org.get("estimated_num_employees") or org.get("num_employees") or 0,
            "industry": org.get("industry", ""),
            "revenue": org.get("annual_revenue_printed", ""),
            "website": org.get("website_url", ""),
            "description": org.get("short_description", ""),
            "linkedin_url": org.get("linkedin_url", ""),
            "country": org.get("country", ""),
        }
    except Exception as exc:
        logger.error("enrich_company_apollo error for %s: %s", domain, exc)
        return {"status": "error", "domain": domain, "error": str(exc)}


@mcp.tool()
def search_prospects_apollo(
    job_titles: str,
    company_sizes: str = "",
    industries: str = "",
    locations: str = "",
    limit: int = 10,
) -> dict:
    """Search for people/prospects matching criteria using Apollo.io People Search API.

    Useful when the Enrichment Agent needs to find specific contacts at a company.

    Args:
        job_titles: Comma-separated titles, e.g. "VP of Sales,Sales Director"
        company_sizes: Comma-separated employee ranges, e.g. "51-200,201-500"
        industries: Comma-separated industries, e.g. "SaaS,Healthcare"
        locations: Comma-separated countries/cities, e.g. "United States,UK"
        limit: Max results (1-25, default 10)

    Returns:
        dict with 'prospects' list and 'total_found'. Each prospect has:
        name, email, title, company, linkedin_url, company_size, industry
    """
    import requests as req

    api_key = os.environ.get("APOLLO_API_KEY", "")
    if not api_key:
        return {"status": "unavailable", "reason": "APOLLO_API_KEY not configured"}

    payload: dict = {
        "per_page": min(limit, 25),
        "page": 1,
        "person_titles": [t.strip() for t in job_titles.split(",") if t.strip()],
    }
    if company_sizes:
        payload["organization_num_employees_ranges"] = [s.strip() for s in company_sizes.split(",") if s.strip()]
    if industries:
        payload["organization_industry_tag_ids"] = [i.strip() for i in industries.split(",") if i.strip()]
    if locations:
        payload["person_locations"] = [l.strip() for l in locations.split(",") if l.strip()]

    try:
        resp = req.post(
            f"{_APOLLO_BASE}/mixed_people/search",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json", "Cache-Control": "no-cache"},
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        people = data.get("people", [])
        prospects = [
            {
                "name": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
                "email": p.get("email", ""),
                "title": p.get("title", ""),
                "company": (p.get("organization") or {}).get("name", ""),
                "company_size": (p.get("organization") or {}).get("estimated_num_employees", ""),
                "industry": (p.get("organization") or {}).get("industry", ""),
                "linkedin_url": p.get("linkedin_url", ""),
                "location": p.get("city", ""),
            }
            for p in people
        ]
        return {
            "status": "ok",
            "source": "apollo_direct",
            "prospects": prospects,
            "total_found": data.get("pagination", {}).get("total_entries", len(prospects)),
        }
    except Exception as exc:
        logger.error("search_prospects_apollo error: %s", exc)
        return {"status": "error", "error": str(exc)}


# ── HubSpot CRM tools ────────────────────────────────────────────────────────
_HUBSPOT_BASE = "https://api.hubapi.com"


def _hs_headers() -> dict:
    token = os.environ.get("HUBSPOT_API_KEY", "")
    if not token:
        raise ValueError("HUBSPOT_API_KEY not set in MCP server env")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@mcp.tool()
def create_hubspot_lead(
    email: str,
    name: str,
    company: str,
    pain_point: str,
    headcount: int = 0,
    route: str = "sme",
) -> dict:
    """Create a HubSpot contact + deal for a new Laabu visitor lead.

    Creates the contact, then creates a deal linked to it. Returns both IDs
    so downstream agents can advance the deal stage.

    Args:
        email:      Visitor's business email.
        name:       Visitor's name (first + last).
        company:    Company name.
        pain_point: Visitor's stated pain point.
        headcount:  Company headcount (0 if unknown).
        route:      "sme" or "enterprise".
    """
    import requests as req

    try:
        hdrs = _hs_headers()
        parts = name.strip().split(" ", 1)
        first, last = parts[0], parts[1] if len(parts) > 1 else ""

        # Create contact — use only standard HubSpot properties
        contact = req.post(
            f"{_HUBSPOT_BASE}/crm/v3/objects/contacts",
            headers=hdrs,
            json={"properties": {
                "email": email, "firstname": first, "lastname": last,
                "company": company,
                "hs_lead_status": "NEW",
            }},
            timeout=15,
        )
        if contact.status_code not in (200, 201, 409):  # 409 = already exists
            return {"status": "error", "step": "contact", "error": contact.text[:200]}

        contact_id = contact.json().get("id") if contact.status_code != 409 else None
        if contact.status_code == 409:
            # Contact exists — fetch their ID
            existing = req.get(
                f"{_HUBSPOT_BASE}/crm/v3/objects/contacts/{email}?idProperty=email",
                headers=hdrs, timeout=10
            )
            contact_id = existing.json().get("id", "unknown")

        # Create deal — store extra data in description (no custom properties needed)
        deal_name = f"{company} — Laabu {'Enterprise' if route == 'enterprise' else 'SME'}"
        description = f"Route: {route} | Headcount: {headcount} | Pain: {pain_point}"
        deal = req.post(
            f"{_HUBSPOT_BASE}/crm/v3/objects/deals",
            headers=hdrs,
            json={"properties": {
                "dealname": deal_name,
                "pipeline": "default",
                "dealstage": "appointmentscheduled",
                "description": description,
            }},
            timeout=15,
        )
        if deal.status_code not in (200, 201):
            return {"status": "error", "step": "deal", "contact_id": contact_id, "error": deal.text[:200]}

        deal_id = deal.json()["id"]

        # Associate contact → deal
        if contact_id:
            req.put(
                f"{_HUBSPOT_BASE}/crm/v4/objects/contacts/{contact_id}/associations/deals/{deal_id}",
                headers=hdrs,
                json=[{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 5}],
                timeout=10,
            )

        return {
            "status": "created",
            "contact_id": contact_id,
            "deal_id": deal_id,
            "deal_name": deal_name,
            "route": route,
            "stage": "New Lead",
        }
    except Exception as exc:
        logger.error("create_hubspot_lead error: %s", exc)
        return {"status": "error", "error": str(exc)}


@mcp.tool()
def advance_hubspot_stage(deal_id: str, stage_name: str) -> dict:
    """Advance a HubSpot deal to the next pipeline stage.

    Args:
        deal_id:    HubSpot deal ID returned by create_hubspot_lead.
        stage_name: Target stage — one of: qualified, needsanalysis, presentationscheduled,
                    decisionmakerboughtin, contractsent, closedwon, closedlost.
    """
    import requests as req

    STAGE_MAP = {
        "new lead":       "appointmentscheduled",
        "qualified":      "qualifiedtobuy",
        "needs analysis": "presentationscheduled",
        "proposal":       "decisionmakerboughtin",
        "negotiation":    "contractsent",
        "closed won":     "closedwon",
        "closed lost":    "closedlost",
        # allow passing HubSpot internal IDs directly
        "appointmentscheduled": "appointmentscheduled",
        "qualifiedtobuy":       "qualifiedtobuy",
        "presentationscheduled":"presentationscheduled",
        "decisionmakerboughtin":"decisionmakerboughtin",
        "contractsent":         "contractsent",
        "closedwon":            "closedwon",
        "closedlost":           "closedlost",
    }
    hs_stage = STAGE_MAP.get(stage_name.lower().strip(), stage_name.lower())

    try:
        resp = req.patch(
            f"{_HUBSPOT_BASE}/crm/v3/objects/deals/{deal_id}",
            headers=_hs_headers(),
            json={"properties": {"dealstage": hs_stage}},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            return {"status": "error", "deal_id": deal_id, "error": resp.text[:200]}
        d = resp.json()
        return {
            "status": "advanced",
            "deal_id": deal_id,
            "new_stage": stage_name,
            "hs_stage_id": hs_stage,
        }
    except Exception as exc:
        logger.error("advance_hubspot_stage error: %s", exc)
        return {"status": "error", "error": str(exc)}


@mcp.tool()
def add_hubspot_note(deal_id: str, note_text: str, contact_id: str = "") -> dict:
    """Add a note to a HubSpot deal (e.g. meeting minutes, call summary).

    Args:
        deal_id:    HubSpot deal ID.
        note_text:  The note body (plain text, up to 65,000 chars).
        contact_id: Optional contact ID to also associate the note with.
    """
    import requests as req

    try:
        hdrs = _hs_headers()
        note = req.post(
            f"{_HUBSPOT_BASE}/crm/v3/objects/notes",
            headers=hdrs,
            json={"properties": {
                "hs_note_body": note_text,
                "hs_timestamp": str(int(__import__("time").time() * 1000)),
            }},
            timeout=15,
        )
        if note.status_code not in (200, 201):
            return {"status": "error", "error": note.text[:200]}

        note_id = note.json()["id"]

        # Associate note → deal
        req.put(
            f"{_HUBSPOT_BASE}/crm/v4/objects/notes/{note_id}/associations/deals/{deal_id}",
            headers=hdrs,
            json=[{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 214}],
            timeout=10,
        )
        # Associate note → contact if provided
        if contact_id:
            req.put(
                f"{_HUBSPOT_BASE}/crm/v4/objects/notes/{note_id}/associations/contacts/{contact_id}",
                headers=hdrs,
                json=[{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}],
                timeout=10,
            )

        return {"status": "added", "note_id": note_id, "deal_id": deal_id, "chars": len(note_text)}
    except Exception as exc:
        logger.error("add_hubspot_note error: %s", exc)
        return {"status": "error", "error": str(exc)}


@mcp.tool()
def get_hubspot_deal(deal_id: str) -> dict:
    """Fetch current deal details from HubSpot, including associated contact emails.

    Args:
        deal_id: HubSpot deal ID.
    """
    import requests as req

    try:
        hdrs = _hs_headers()
        resp = req.get(
            f"{_HUBSPOT_BASE}/crm/v3/objects/deals/{deal_id}"
            "?properties=dealname,dealstage,amount,laabu_route,laabu_headcount,laabu_pain_point,description",
            headers=hdrs,
            timeout=15,
        )
        if resp.status_code != 200:
            return {"status": "error", "error": resp.text[:200]}
        props = resp.json().get("properties", {})

        # Fetch associated contacts to get visitor email
        contacts_resp = req.get(
            f"{_HUBSPOT_BASE}/crm/v3/objects/deals/{deal_id}/associations/contacts",
            headers=hdrs,
            timeout=10,
        )
        visitor_email = None
        contact_id = None
        if contacts_resp.status_code == 200:
            contact_ids = [r["id"] for r in contacts_resp.json().get("results", [])]
            if contact_ids:
                contact_id = contact_ids[0]
                c = req.get(
                    f"{_HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}?properties=email",
                    headers=hdrs,
                    timeout=10,
                )
                if c.status_code == 200:
                    visitor_email = c.json().get("properties", {}).get("email")

        return {
            "status": "ok",
            "deal_id": deal_id,
            "deal_name": props.get("dealname"),
            "stage": props.get("dealstage"),
            "amount": props.get("amount"),
            "route": props.get("laabu_route"),
            "headcount": props.get("laabu_headcount"),
            "pain_point": props.get("laabu_pain_point"),
            "description": props.get("description"),
            "visitor_email": visitor_email,
            "contact_id": contact_id,
        }
    except Exception as exc:
        logger.error("get_hubspot_deal error: %s", exc)
        return {"status": "error", "error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
