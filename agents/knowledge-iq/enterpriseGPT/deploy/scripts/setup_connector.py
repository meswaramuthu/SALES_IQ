#!/usr/bin/env python3
"""Validate and configure a Knowledge IQ data connector in tools_config.json.

Validates credentials against the real API before touching any config.
On success, merges the connector config into tools_config.json and uploads
it to GCS (or writes it back to a local file with --config-file).

Usage examples:
    uv run python scripts/setup_connector.py sharepoint \\
        --tenant-id UUID --client-id UUID --client-secret "secret" \\
        --site-url "https://org.sharepoint.com/sites/Name" --search-region APC

    uv run python scripts/setup_connector.py github \\
        --token env:GITHUB_TOKEN --default-org stratova-ai

    uv run python scripts/setup_connector.py jira \\
        --url https://org.atlassian.net --username admin@org.com --api-token TOKEN

    uv run python scripts/setup_connector.py confluence \\
        --url https://org.atlassian.net/wiki --username admin@org.com --api-token TOKEN

    uv run python scripts/setup_connector.py gmail \\
        --service-account-key-gcs-uri gs://bucket/sa.json --user-email user@domain.com

    uv run python scripts/setup_connector.py gdrive \\
        --service-account-key-gcs-uri gs://bucket/sa.json --user-email user@domain.com

    uv run python scripts/setup_connector.py hubspot \\
        --resource-name "projects/X/locations/Y/reasoningEngines/Z"

    uv run python scripts/setup_connector.py apollo \\
        --resource-name "projects/X/locations/Y/reasoningEngines/Z"

Global flags (before the connector subcommand):
    --gcs-uri       GCS URI for tools_config.json (default: TOOLS_CONFIG_GCS_URI env var)
    --config-file   Local JSON file to read/write instead of GCS
    --dry-run       Validate only, do NOT upload
    --disable       Set enabled=false instead of true
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Connector-to-config-key mapping
# (section, key_in_section)
# ---------------------------------------------------------------------------
CONNECTOR_MAP: dict[str, tuple[str, str]] = {
    "sharepoint": ("tools",      "sharepoint"),
    "github":     ("tools",      "github"),
    "jira":       ("tools",      "jira"),
    "confluence": ("tools",      "confluence"),
    "gmail":      ("tools",      "gmail"),
    "gdrive":     ("tools",      "gdrive"),
    "hubspot":    ("sub_agents", "crm_agent"),
    "apollo":     ("sub_agents", "enrichment_agent"),
}

SUB_AGENT_DESCRIPTIONS: dict[str, str] = {
    "hubspot": "HubSpot CRM operations",
    "apollo":  "Company enrichment",
}


# ---------------------------------------------------------------------------
# Secret resolution
# ---------------------------------------------------------------------------
def _resolve_secret(value: str) -> str:
    """Return the literal credential value for API calls.

    If value is 'env:VAR_NAME', reads from the environment.
    The *stored* config value always remains the original string.
    """
    if value.startswith("env:"):
        var = value[4:]
        resolved = os.environ.get(var)
        if resolved is None:
            sys.exit(f"  [FAIL] env var '{var}' is not set in the environment")
        return resolved
    return value


# ---------------------------------------------------------------------------
# GCS helpers (inline — same pattern as upload_config.py)
# ---------------------------------------------------------------------------
def _parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    m = re.match(r"gs://([^/]+)/(.+)", gcs_uri)
    if not m:
        sys.exit(f"Invalid GCS URI: {gcs_uri}")
    return m.group(1), m.group(2)


def _gcs_read_text(gcs_uri: str) -> str:
    from google.cloud import storage  # noqa: PLC0415
    bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
    client = storage.Client()
    return client.bucket(bucket_name).blob(blob_name).download_as_text()


def _gcs_read_bytes(gcs_uri: str) -> bytes:
    from google.cloud import storage  # noqa: PLC0415
    bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
    client = storage.Client()
    return client.bucket(bucket_name).blob(blob_name).download_as_bytes()


def _gcs_write_text(gcs_uri: str, text: str) -> None:
    from google.cloud import storage  # noqa: PLC0415
    bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
    client = storage.Client()
    client.bucket(bucket_name).blob(blob_name).upload_from_string(
        text, content_type="application/json"
    )


# ---------------------------------------------------------------------------
# Config load / save / merge
# ---------------------------------------------------------------------------
def load_config(args: argparse.Namespace) -> dict[str, Any]:
    if args.config_file:
        path = Path(args.config_file)
        if not path.exists():
            sys.exit(f"Error: {path} not found")
        return json.loads(path.read_text())

    if not args.gcs_uri:
        sys.exit(
            "Error: provide --gcs-uri, --config-file, or set TOOLS_CONFIG_GCS_URI"
        )
    try:
        return json.loads(_gcs_read_text(args.gcs_uri))
    except Exception as exc:
        sys.exit(
            f"Error reading config from GCS: {exc}\n"
            "Hint: use --config-file config/tools_config.json to test locally"
        )


def save_config(config: dict[str, Any], args: argparse.Namespace) -> None:
    text = json.dumps(config, indent=2)
    if args.config_file:
        Path(args.config_file).write_text(text)
        print(f"  [OK] Config written to {args.config_file}")
        return
    try:
        _gcs_write_text(args.gcs_uri, text)
        print(f"  [OK] Config uploaded to {args.gcs_uri}")
    except Exception as exc:
        sys.exit(f"Error uploading config to GCS: {exc}")


def merge_connector(
    config: dict[str, Any],
    connector: str,
    section: str,
    key: str,
    cfg_dict: dict[str, Any],
    enabled: bool,
) -> None:
    """Merge cfg_dict into the connector's section, leaving all other connectors untouched."""
    config.setdefault(section, {})

    if section == "tools":
        entry = config[section].setdefault(key, {"enabled": False, "config": {}})
        entry.setdefault("config", {})
        entry["config"].update(cfg_dict)
        entry["enabled"] = enabled
    else:
        # sub_agents — flat structure (no nested "config" key)
        entry = config[section].setdefault(key, {"enabled": False, "resource_name": "", "agent_card_url": "", "description": ""})
        entry.update(cfg_dict)
        entry["enabled"] = enabled
        if not entry.get("description"):
            entry["description"] = SUB_AGENT_DESCRIPTIONS.get(connector, "")


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def validate_sharepoint(args: argparse.Namespace) -> None:
    import msal  # noqa: PLC0415
    import requests  # noqa: PLC0415

    secret = _resolve_secret(args.client_secret)
    authority = f"https://login.microsoftonline.com/{args.tenant_id}"
    app = msal.ConfidentialClientApplication(
        args.client_id, authority=authority, client_credential=secret
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        error = result.get("error_description") or result.get("error") or str(result)
        raise RuntimeError(f"Azure AD token acquisition failed: {error}")
    print(f"  [OK] Token acquired from Azure AD (tenant: {args.tenant_id[:8]}...)")

    token = result["access_token"]
    resp = requests.get(
        "https://graph.microsoft.com/v1.0/sites?$top=1",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    print("  [OK] Microsoft Graph API reachable")


def validate_github(args: argparse.Namespace) -> None:
    import requests  # noqa: PLC0415

    token = _resolve_secret(args.token)
    resp = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
        timeout=15,
    )
    if resp.status_code == 401:
        raise RuntimeError("Authentication rejected: invalid GitHub token")
    resp.raise_for_status()
    login = resp.json().get("login", "unknown")
    print(f"  [OK] Authenticated as GitHub user: {login}")


def validate_jira(args: argparse.Namespace) -> None:
    import requests  # noqa: PLC0415
    from requests.auth import HTTPBasicAuth  # noqa: PLC0415

    api_token = _resolve_secret(args.api_token)
    url = args.url.rstrip("/")
    resp = requests.get(
        f"{url}/rest/api/3/myself",
        auth=HTTPBasicAuth(args.username, api_token),
        timeout=15,
    )
    if resp.status_code in (401, 403):
        raise RuntimeError(f"Authentication rejected: {resp.status_code} {resp.reason}")
    resp.raise_for_status()
    display_name = resp.json().get("displayName", args.username)
    print(f"  [OK] Authenticated as Jira user: {display_name}")


def validate_confluence(args: argparse.Namespace) -> None:
    import requests  # noqa: PLC0415
    from requests.auth import HTTPBasicAuth  # noqa: PLC0415

    api_token = _resolve_secret(args.api_token)
    url = args.url.rstrip("/")
    resp = requests.get(
        f"{url}/wiki/rest/api/user/current",
        auth=HTTPBasicAuth(args.username, api_token),
        timeout=15,
    )
    if resp.status_code in (401, 403):
        raise RuntimeError(f"Authentication rejected: {resp.status_code} {resp.reason}")
    resp.raise_for_status()
    display_name = resp.json().get("displayName", args.username)
    print(f"  [OK] Authenticated as Confluence user: {display_name}")


def _validate_google_sa(gcs_uri: str, user_email: str, scopes: list[str], service_label: str) -> None:
    """Shared validator for Gmail and Google Drive (both use a delegated SA key in GCS)."""
    import json as _json  # noqa: PLC0415

    import google.auth.transport.requests  # noqa: PLC0415
    from google.oauth2 import service_account  # noqa: PLC0415

    try:
        key_bytes = _gcs_read_bytes(gcs_uri)
    except Exception as exc:
        raise RuntimeError(f"Could not download service account key from GCS: {exc}") from exc

    try:
        key_data = _json.loads(key_bytes)
    except Exception as exc:
        raise RuntimeError(f"Service account key is not valid JSON: {exc}") from exc

    try:
        creds = service_account.Credentials.from_service_account_info(
            key_data,
            scopes=scopes,
            subject=user_email,
        )
        creds.refresh(google.auth.transport.requests.Request())
    except Exception as exc:
        raise RuntimeError(f"Service account credential refresh failed: {exc}") from exc

    print(f"  [OK] Service account credentials valid for {user_email} ({service_label})")


def validate_gmail(args: argparse.Namespace) -> None:
    _validate_google_sa(
        args.service_account_key_gcs_uri,
        args.user_email,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        service_label="Gmail",
    )


def validate_gdrive(args: argparse.Namespace) -> None:
    _validate_google_sa(
        args.service_account_key_gcs_uri,
        args.user_email,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
        service_label="Google Drive",
    )


def validate_sub_agent(args: argparse.Namespace) -> None:
    resource_name = args.resource_name
    m = re.match(r"projects/([^/]+)/locations/([^/]+)/reasoningEngines/([^/]+)", resource_name)
    if not m:
        raise RuntimeError(
            f"Invalid resource_name format. Expected: "
            f"projects/PROJECT/locations/LOCATION/reasoningEngines/ID\n"
            f"Got: {resource_name}"
        )
    project, location = m.group(1), m.group(2)

    import vertexai  # noqa: PLC0415
    from vertexai import agent_engines  # noqa: PLC0415

    vertexai.init(project=project, location=location)
    try:
        agent = agent_engines.get(resource_name)
    except Exception as exc:
        raise RuntimeError(f"Agent Engine resource not found: {exc}") from exc

    display_name = getattr(agent, "display_name", resource_name)
    print(f"  [OK] Vertex AI Agent Engine resource exists: {display_name}")


VALIDATORS = {
    "sharepoint": validate_sharepoint,
    "github":     validate_github,
    "jira":       validate_jira,
    "confluence": validate_confluence,
    "gmail":      validate_gmail,
    "gdrive":     validate_gdrive,
    "hubspot":    validate_sub_agent,
    "apollo":     validate_sub_agent,
}


# ---------------------------------------------------------------------------
# Config builders — return dict to store in the connector's config section
# ---------------------------------------------------------------------------
def build_sharepoint_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "tenant_id":     args.tenant_id,
        "client_id":     args.client_id,
        "client_secret": args.client_secret,  # stored as-is (env:VAR or literal)
    }
    if args.site_url:
        cfg["site_url"] = args.site_url
    if args.search_region:
        cfg["search_region"] = args.search_region
    return cfg


def build_github_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg: dict[str, Any] = {"token": args.token}  # stored as-is
    if args.default_org:
        cfg["default_org"] = args.default_org
    if args.default_repo:
        cfg["default_repo"] = args.default_repo
    return cfg


def build_jira_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "url":       args.url,
        "username":  args.username,
        "api_token": args.api_token,  # stored as-is
    }


def build_confluence_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "url":       args.url,
        "username":  args.username,
        "api_token": args.api_token,  # stored as-is
    }


def build_gmail_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "service_account_key_gcs_uri": args.service_account_key_gcs_uri,
        "user_email":                  args.user_email,
    }
    if args.max_results:
        cfg["max_results"] = args.max_results
    return cfg


def build_gdrive_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "service_account_key_gcs_uri": args.service_account_key_gcs_uri,
        "user_email":                  args.user_email,
    }


def build_sub_agent_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg: dict[str, Any] = {"resource_name": args.resource_name}
    if getattr(args, "agent_card_url", ""):
        cfg["agent_card_url"] = args.agent_card_url
    return cfg


BUILDERS = {
    "sharepoint": build_sharepoint_config,
    "github":     build_github_config,
    "jira":       build_jira_config,
    "confluence": build_confluence_config,
    "gmail":      build_gmail_config,
    "gdrive":     build_gdrive_config,
    "hubspot":    build_sub_agent_config,
    "apollo":     build_sub_agent_config,
}


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setup_connector",
        description="Validate and configure a Knowledge IQ connector in tools_config.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--gcs-uri",
        default=os.environ.get("TOOLS_CONFIG_GCS_URI"),
        help="GCS URI for tools_config.json (default: TOOLS_CONFIG_GCS_URI env var)",
    )
    parser.add_argument(
        "--config-file",
        help="Local JSON file to read/write instead of GCS (for offline testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only, do NOT upload config",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Set enabled=false instead of true",
    )

    subs = parser.add_subparsers(dest="connector", required=True)

    # sharepoint
    sp = subs.add_parser("sharepoint", help="Microsoft SharePoint via Graph API")
    sp.add_argument("--tenant-id",    required=True, help="Azure AD tenant ID (Directory ID)")
    sp.add_argument("--client-id",    required=True, help="App registration client ID")
    sp.add_argument("--client-secret",required=True, help="Client secret or 'env:VAR_NAME'")
    sp.add_argument("--site-url",     default="",    help="Default SharePoint site URL")
    sp.add_argument("--search-region",default="APC", choices=["NAM", "EUR", "APC"],
                    help="Microsoft Search region (default: APC)")

    # github
    gh = subs.add_parser("github", help="GitHub via Personal Access Token")
    gh.add_argument("--token",        required=True, help="GitHub PAT or 'env:GITHUB_TOKEN'")
    gh.add_argument("--default-org",  default="",    help="Default GitHub organization")
    gh.add_argument("--default-repo", default="",    help="Default repo in owner/repo format")

    # jira
    jira = subs.add_parser("jira", help="Atlassian Jira Cloud")
    jira.add_argument("--url",       required=True, help="Jira URL, e.g. https://org.atlassian.net")
    jira.add_argument("--username",  required=True, help="Admin email address")
    jira.add_argument("--api-token", required=True, help="Jira API token or 'env:JIRA_API_TOKEN'")

    # confluence
    conf = subs.add_parser("confluence", help="Atlassian Confluence Cloud")
    conf.add_argument("--url",       required=True, help="Confluence URL, e.g. https://org.atlassian.net/wiki")
    conf.add_argument("--username",  required=True, help="Admin email address")
    conf.add_argument("--api-token", required=True, help="Confluence API token or 'env:CONFLUENCE_API_TOKEN'")

    # gmail
    gmail = subs.add_parser("gmail", help="Google Gmail via service account with DWD")
    gmail.add_argument("--service-account-key-gcs-uri", required=True,
                       help="GCS URI to service account JSON key file")
    gmail.add_argument("--user-email", required=True, help="User email for domain-wide delegation")
    gmail.add_argument("--max-results", type=int, default=20, help="Max emails per query (default: 20)")

    # gdrive
    gdrive = subs.add_parser("gdrive", help="Google Drive via service account with DWD")
    gdrive.add_argument("--service-account-key-gcs-uri", required=True,
                        help="GCS URI to service account JSON key file")
    gdrive.add_argument("--user-email", required=True, help="User email for domain-wide delegation")

    # hubspot (maps to sub_agents.crm_agent)
    hubspot = subs.add_parser("hubspot", help="HubSpot CRM via sub-agent (crm_agent)")
    hubspot.add_argument("--resource-name", required=True,
                         help="Vertex AI Agent Engine resource name: projects/P/locations/L/reasoningEngines/ID")
    hubspot.add_argument("--agent-card-url", default="",
                         help="GCS URI to agent-card.json (optional)")

    # apollo (maps to sub_agents.enrichment_agent)
    apollo = subs.add_parser("apollo", help="Apollo/Enrichment via sub-agent (enrichment_agent)")
    apollo.add_argument("--resource-name", required=True,
                        help="Vertex AI Agent Engine resource name: projects/P/locations/L/reasoningEngines/ID")
    apollo.add_argument("--agent-card-url", default="",
                        help="GCS URI to agent-card.json (optional)")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Normalise dashes to underscores in attribute names (argparse does this,
    # but let's be explicit for --service-account-key-gcs-uri)
    if hasattr(args, "service_account_key_gcs_uri"):
        pass  # already normalised by argparse

    print(f"Validating {args.connector} connector...")

    try:
        VALIDATORS[args.connector](args)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"  [FAIL] {exc}")
        print("\nValidation failed. Config was NOT updated.")
        sys.exit(1)

    print("Validation passed.")

    if args.dry_run:
        print("Dry run — skipping config update.")
        sys.exit(0)

    print("Updating tools_config.json...")
    config = load_config(args)

    section, key = CONNECTOR_MAP[args.connector]
    cfg_dict = BUILDERS[args.connector](args)
    merge_connector(config, args.connector, section, key, cfg_dict, enabled=not args.disable)
    save_config(config, args)

    action = "disabled" if args.disable else "enabled"
    print(f"{args.connector} connector {action}. Changes take effect within 60 seconds.")


if __name__ == "__main__":
    main()
