"""Email MCP — Gmail email sending (service account + DWD) + GCS template loader.

Uses the same Gmail service account already configured for KnowledgeIQ and other
Stratova agents. No SendGrid key needed — the SA key lives in GCS.

Env vars required:
  GMAIL_SA_KEY_GCS_URI  — GCS path to SA JSON e.g. gs://bucket/creds/google-sa.json
  GMAIL_USER_EMAIL      — Gmail address to send as e.g. abdul@stratova.ai
  EMAIL_TEMPLATES_BUCKET — GCS bucket for HTML templates (default: stratova-platform)
  GOOGLE_CLOUD_PROJECT  — GCP project ID
"""
from __future__ import annotations

import base64
import json
import logging
import os
_PORT = int(os.environ.get("PORT", 8080))

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("stratova-email", host="0.0.0.0", port=_PORT)

_gmail_service = None


def _get_gmail_service():
    """Build a Gmail send service using the SA key stored in GCS.

    Follows the same pattern as knowledge-iq and ai-sdr:
      - Reads SA JSON from GCS (GMAIL_SA_KEY_GCS_URI)
      - Uses domain-wide delegation to impersonate GMAIL_USER_EMAIL
      - Scoped to gmail.send only
    """
    global _gmail_service
    if _gmail_service is not None:
        return _gmail_service

    from google.cloud import storage
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    sa_gcs_uri = os.environ.get("GMAIL_SA_KEY_GCS_URI", "")
    gmail_user = os.environ.get("GMAIL_USER_EMAIL", "")

    if not sa_gcs_uri or not gmail_user:
        raise ValueError(
            "GMAIL_SA_KEY_GCS_URI and GMAIL_USER_EMAIL must be set. "
            f"Got: SA_GCS_URI={'set' if sa_gcs_uri else 'MISSING'}, "
            f"USER={'set' if gmail_user else 'MISSING'}"
        )

    # Read SA key JSON from GCS
    m = sa_gcs_uri.replace("gs://", "").split("/", 1)
    bucket_name, blob_path = m[0], m[1]
    gcs = storage.Client()
    key_json = json.loads(gcs.bucket(bucket_name).blob(blob_path).download_as_text())

    # Build credentials with DWD impersonation
    creds = Credentials.from_service_account_info(
        key_json,
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    ).with_subject(gmail_user)

    _gmail_service = build("gmail", "v1", credentials=creds)
    return _gmail_service


def _build_raw_message(to_email: str, subject: str, body: str,
                        from_email: str, from_name: str) -> str:
    """Encode an email as base64url for the Gmail API."""
    import email.mime.multipart
    import email.mime.text

    msg = email.mime.multipart.MIMEMultipart("alternative")
    msg["To"]      = to_email
    msg["From"]    = f"{from_name} <{from_email}>" if from_name else from_email
    msg["Subject"] = subject
    msg.attach(email.mime.text.MIMEText(body, "html"))
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


@mcp.tool()
def send_email(
    to_email: str,
    subject: str,
    body: str,
    from_email: str = "",
    from_name: str = "JANY from Laabu",
) -> dict:
    """Send an HTML email via Gmail (service account + domain-wide delegation).

    Uses the same Gmail SA already configured for the Stratova project
    (GMAIL_SA_KEY_GCS_URI). No SendGrid key required.

    Args:
        to_email:   Recipient email address.
        subject:    Email subject line.
        body:       HTML body content.
        from_email: Sender address — defaults to GMAIL_USER_EMAIL env var.
        from_name:  Sender display name (default: JANY from Laabu).
    """
    try:
        sender = from_email or os.environ.get("GMAIL_USER_EMAIL", "")
        raw    = _build_raw_message(to_email, subject, body, sender, from_name)
        svc    = _get_gmail_service()
        result = svc.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return {
            "status":     "sent",
            "provider":   "gmail",
            "gmail_id":   result.get("id"),
            "to":         to_email,
            "subject":    subject,
        }
    except Exception as exc:
        logger.error("send_email to %s error: %s", to_email, exc)
        return {"status": "error", "to": to_email, "error": str(exc)}


@mcp.tool()
def get_email_template(template_name: str) -> str:
    """Load an HTML email template from the GCS templates bucket.

    Templates live at:
      gs://{EMAIL_TEMPLATES_BUCKET}/mcp-servers/email/templates/{template_name}.html

    Available templates: safety-net, package-followup, meeting-confirm

    Args:
        template_name: Template name without extension e.g. "safety-net".
    """
    try:
        from google.cloud import storage

        bucket_name = os.environ.get("EMAIL_TEMPLATES_BUCKET", "stratova-platform")
        blob_path   = f"mcp-servers/email/templates/{template_name}.html"
        client      = storage.Client()
        return client.bucket(bucket_name).blob(blob_path).download_as_text()
    except Exception as exc:
        logger.error("get_email_template %s error: %s", template_name, exc)
        return f"<p>Template '{template_name}' not found. Error: {exc}</p>"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
