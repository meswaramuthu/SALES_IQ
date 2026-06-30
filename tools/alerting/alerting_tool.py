"""Threshold-based alerting and email reporting for Ops IQ.

Checks metrics against configured thresholds and dispatches emails via the
shared Email MCP server (Gmail / service-account delegation). The email agent
itself is NOT called via A2A — the MCP server is called directly so that
send_email is always available regardless of the email agent's A2A state.

Email TO addresses and thresholds live in tools_config.json / env vars so
recipients and sensitivity can be tuned without redeploying.

tools_config.json schema (under tools.alerting.config):
    {
      "email_mcp_url": "env:EMAIL_MCP_URL",
      "from_email": "ops-iq@stratova.ai",
      "from_name": "Ops IQ — Stratova AI",
      "to_emails": ["admin@company.com", "ops@company.com"],
      "thresholds": {
        "error_rate_pct": 2.0,
        "latency_p99_ms": 30000,
        "token_daily_budget": 5000000,
        "request_daily_budget": 10000,
        "quota_utilisation_pct": 80
      }
    }

Env vars:
    EMAIL_MCP_URL   — URL of the email MCP server (e.g. https://stratova-email-mcp-*.run.app/mcp)
    ALERT_TO_EMAILS — comma-separated fallback when to_emails is not a list in config
    ALERT_FROM_NAME — sender display name
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Callable

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLDS = {
    "error_rate_pct": 2.0,            # alert when any model error rate > 2%
    "latency_p99_ms": 30000.0,        # alert when p99 > 30s (Live/streaming APIs can be 60–300s)
    "token_daily_budget": 5_000_000,  # alert when 24h tokens > 5 M
    "request_daily_budget": 10_000,   # alert when 24h requests > 10 k
    "quota_utilisation_pct": 80.0,    # alert when quota utilisation > 80%
}

# Models whose latency metric reflects full session duration, not single-request p99.
# These are excluded from the latency threshold check to avoid false alerts.
_LATENCY_EXCLUDE_PATTERNS = ("live", "audio", "realtime")


def get_tools() -> list[Callable]:
    from config import get_config

    def _check_enabled() -> dict | None:
        cfg = get_config()
        tc = cfg.tools.get("alerting")
        if not tc or not tc.enabled:
            return {"status": "disabled", "message": "Alerting is currently disabled via feature flag."}
        return None

    def _get_alerting_config() -> dict:
        cfg = get_config()
        tc = cfg.tools.get("alerting")
        return tc.config if tc else {}

    def _get_thresholds() -> dict:
        raw = _get_alerting_config().get("thresholds", {})
        return {**_DEFAULT_THRESHOLDS, **raw}

    def _get_recipients() -> list[str]:
        ac = _get_alerting_config()
        to_raw = ac.get("to_emails", os.environ.get("ALERT_TO_EMAILS", ""))
        if isinstance(to_raw, list):
            return [e.strip() for e in to_raw if e.strip()]
        return [e.strip() for e in to_raw.split(",") if e.strip()]

    def _get_email_mcp_url() -> str:
        ac = _get_alerting_config()
        return (
            ac.get("email_mcp_url")
            or os.environ.get("EMAIL_MCP_URL", "")
        )

    def _get_from_email() -> str:
        return _get_alerting_config().get("from_email", "ops-iq@stratova.ai")

    def _get_from_name() -> str:
        return _get_alerting_config().get("from_name", os.environ.get("ALERT_FROM_NAME", "Ops IQ — Stratova AI"))

    def _get_id_token(audience: str) -> str:
        """Fetch a Google ID token for authenticating to a Cloud Run service.

        Works in two modes:
        - Cloud Run / GCE: service account via metadata server (fetch_id_token)
        - Local dev: user credentials via `gcloud auth print-identity-token`
        """
        try:
            import google.auth.transport.requests
            from google.oauth2 import id_token as _id_token
            request = google.auth.transport.requests.Request()
            return _id_token.fetch_id_token(request, audience)
        except Exception:
            import subprocess
            result = subprocess.run(
                ["gcloud", "auth", "print-identity-token"],
                capture_output=True, text=True, check=True,
            )
            return result.stdout.strip()

    def _dispatch_email(to_emails: list[str], subject: str, body_html: str) -> dict:
        """Send email via the email MCP server directly (no A2A agent hop needed).

        Uses the MCP StreamableHTTP client with a Google ID token for auth.
        Sends one request per recipient so each person gets a personal copy.
        """
        mcp_url = _get_email_mcp_url()
        if not mcp_url:
            logger.warning("EMAIL_MCP_URL not set — email skipped")
            return {
                "status": "skipped",
                "message": "EMAIL_MCP_URL is not configured. "
                           "Set it in tools_config.json (alerting.config.email_mcp_url) "
                           "or the EMAIL_MCP_URL env var.",
            }
        if not to_emails:
            return {"status": "skipped", "message": "No recipient addresses configured in ALERT_TO_EMAILS."}

        import asyncio

        async def _send_via_mcp():
            from mcp.client.streamable_http import streamablehttp_client
            from mcp import ClientSession

            # Derive the audience from the base URL (strip /mcp path if present)
            base_url = mcp_url.rstrip("/mcp").rstrip("/")
            if not base_url.endswith("/mcp"):
                full_mcp_url = mcp_url if mcp_url.endswith("/mcp") else mcp_url.rstrip("/") + "/mcp"
            else:
                full_mcp_url = mcp_url

            audience = base_url
            try:
                token = _get_id_token(audience)
                headers = {"Authorization": f"Bearer {token}"}
            except Exception as exc:
                logger.warning("Could not get ID token (%s) — trying unauthenticated", exc)
                headers = {}

            async with streamablehttp_client(url=full_mcp_url, headers=headers) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    results = []
                    for recipient in to_emails:
                        result = await session.call_tool("send_email", {
                            "to_email": recipient,
                            "subject": subject,
                            "body": body_html,
                            "from_email": _get_from_email(),
                            "from_name": _get_from_name(),
                        })
                        results.append({"to": recipient, "content": str(result.content)[:200]})
                    return results

        try:
            results = asyncio.run(_send_via_mcp())
            logger.info("Email sent via MCP: subject='%s' to=%s", subject, to_emails)
            return {
                "status": "sent",
                "recipients": to_emails,
                "subject": subject,
                "results": results,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("Email MCP dispatch failed: %s", err)
            return {"status": "error", "message": f"MCP email dispatch failed: {err[:300]}"}

    def _fmt_int(v) -> str:
        try:
            return f"{int(v):,}"
        except (TypeError, ValueError):
            return str(v or "N/A")

    def _format_alert_body(violations: list[dict], hours: int, project: str) -> str:
        rows = "".join(
            f"<tr style='background:#fff3cd'>"
            f"<td style='padding:8px;border:1px solid #dee2e6'><b>{v['check']}</b></td>"
            f"<td style='padding:8px;border:1px solid #dee2e6;color:#dc3545'>{v['value']}</td>"
            f"<td style='padding:8px;border:1px solid #dee2e6'>{v['threshold']}</td>"
            f"<td style='padding:8px;border:1px solid #dee2e6'>{v['detail']}</td>"
            f"</tr>"
            for v in violations
        )
        return f"""<html><body style="font-family:Arial,sans-serif;max-width:680px;margin:auto;color:#212529">
  <div style="background:#dc3545;padding:20px;border-radius:6px 6px 0 0">
    <h2 style="color:#fff;margin:0">&#x26A0; Ops IQ Alert &mdash; {project}</h2>
    <p style="color:#f8d7da;margin:4px 0 0">{len(violations)} threshold violation(s) &bull; last {hours}h</p>
  </div>
  <div style="border:1px solid #dee2e6;border-top:none;padding:20px;border-radius:0 0 6px 6px">
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:#f8f9fa">
        <th style="padding:8px;border:1px solid #dee2e6;text-align:left">Check</th>
        <th style="padding:8px;border:1px solid #dee2e6;text-align:left">Current</th>
        <th style="padding:8px;border:1px solid #dee2e6;text-align:left">Threshold</th>
        <th style="padding:8px;border:1px solid #dee2e6;text-align:left">Detail</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p style="margin-top:16px">
      <a href="https://console.cloud.google.com/monitoring?project={project}">View Cloud Monitoring &rarr;</a>
    </p>
    <hr style="border:none;border-top:1px solid #dee2e6;margin:12px 0">
    <p style="color:#6c757d;font-size:11px">Stratova AI &mdash; Ops IQ automated alert</p>
  </div>
</body></html>"""

    def _format_report_body(metrics: dict, violations: list[dict], hours: int, project: str) -> str:
        tokens = metrics.get("tokens", {})
        reqs = metrics.get("requests", {})
        errors = metrics.get("errors", {})
        latency = metrics.get("latency", {})

        status_color = "#dc3545" if violations else "#198754"
        status_text = f"&#x26A0; {len(violations)} ALERT(S)" if violations else "&#x2705; HEALTHY"

        def _model_rows_tokens(items):
            if not items:
                return "<tr><td colspan='2' style='padding:6px;color:#6c757d'>No data</td></tr>"
            return "".join(
                f"<tr><td style='padding:5px 8px;border-bottom:1px solid #f0f0f0'>{r['model']}</td>"
                f"<td style='padding:5px 8px;border-bottom:1px solid #f0f0f0;text-align:right'>{_fmt_int(r.get('total_tokens'))}</td></tr>"
                for r in items[:5]
            )

        def _model_rows_reqs(items):
            if not items:
                return "<tr><td colspan='2' style='padding:6px;color:#6c757d'>No data</td></tr>"
            return "".join(
                f"<tr><td style='padding:5px 8px;border-bottom:1px solid #f0f0f0'>{r['model']}</td>"
                f"<td style='padding:5px 8px;border-bottom:1px solid #f0f0f0;text-align:right'>{_fmt_int(r.get('request_count'))}</td></tr>"
                for r in items[:5]
            )

        violation_block = ""
        if violations:
            vrows = "".join(
                f"<li style='color:#dc3545;margin:4px 0'><b>{v['check']}</b>: {v['value']} "
                f"(threshold: {v['threshold']}) &mdash; {v['detail']}</li>"
                for v in violations
            )
            violation_block = f"<h3 style='color:#dc3545'>&#x26A0; Threshold Violations</h3><ul>{vrows}</ul>"
        else:
            violation_block = "<p style='color:#198754'>&#x2705; All metrics within configured thresholds.</p>"

        lat_summary = ", ".join(
            f"{r['model'].split('-')[0]}: {r.get('p99_ms','?')}ms p99"
            for r in latency.get("by_model", [])[:3]
            if "live" not in r.get("model","").lower()
        ) or "N/A"

        return f"""<html><body style="font-family:Arial,sans-serif;max-width:680px;margin:auto;color:#212529">
  <div style="background:#0d6efd;padding:20px;border-radius:6px 6px 0 0">
    <h2 style="color:#fff;margin:0">Ops IQ Status Report &mdash; {project}</h2>
    <p style="color:#cfe2ff;margin:4px 0 0">Platform health summary &bull; last {hours} hours</p>
  </div>
  <div style="border:1px solid #dee2e6;border-top:none;padding:20px;border-radius:0 0 6px 6px">

    <div style="display:flex;gap:10px;margin-bottom:16px">
      <div style="flex:1;padding:12px;background:#f8f9fa;border-radius:6px;text-align:center">
        <div style="font-size:22px;font-weight:bold;color:#0d6efd">{_fmt_int(tokens.get('total_tokens'))}</div>
        <div style="font-size:11px;color:#6c757d;margin-top:2px">Total Tokens</div>
      </div>
      <div style="flex:1;padding:12px;background:#f8f9fa;border-radius:6px;text-align:center">
        <div style="font-size:22px;font-weight:bold;color:#0d6efd">{_fmt_int(reqs.get('total_requests'))}</div>
        <div style="font-size:11px;color:#6c757d;margin-top:2px">API Requests</div>
      </div>
      <div style="flex:1;padding:12px;border:2px solid {status_color};border-radius:6px;text-align:center">
        <div style="font-size:16px;font-weight:bold;color:{status_color}">{status_text}</div>
        <div style="font-size:11px;color:#6c757d;margin-top:2px">Overall Status</div>
      </div>
    </div>

    {violation_block}

    <div style="display:flex;gap:16px;margin-top:16px">
      <div style="flex:1">
        <h4 style="margin:0 0 6px;font-size:13px">Token Usage by Model</h4>
        <table style="width:100%;border-collapse:collapse;font-size:12px">
          <thead><tr style="background:#f8f9fa">
            <th style="padding:5px 8px;text-align:left">Model</th>
            <th style="padding:5px 8px;text-align:right">Tokens</th>
          </tr></thead>
          <tbody>{_model_rows_tokens(tokens.get("by_model",[]))}</tbody>
        </table>
      </div>
      <div style="flex:1">
        <h4 style="margin:0 0 6px;font-size:13px">Requests by Model</h4>
        <table style="width:100%;border-collapse:collapse;font-size:12px">
          <thead><tr style="background:#f8f9fa">
            <th style="padding:5px 8px;text-align:left">Model</th>
            <th style="padding:5px 8px;text-align:right">Requests</th>
          </tr></thead>
          <tbody>{_model_rows_reqs(reqs.get("by_model",[]))}</tbody>
        </table>
      </div>
    </div>

    <div style="margin-top:14px;padding:10px 14px;background:#f8f9fa;border-radius:6px;font-size:12px">
      <b>Errors:</b> {len(errors.get('alerts',[]))} alert(s) &nbsp;|&nbsp;
      <b>Latency (p99, non-live):</b> {lat_summary}
    </div>

    <p style="margin-top:14px">
      <a href="https://console.cloud.google.com/monitoring?project={project}">Cloud Monitoring Console &rarr;</a>
    </p>
    <hr style="border:none;border-top:1px solid #dee2e6;margin:12px 0">
    <p style="color:#6c757d;font-size:11px">Stratova AI &mdash; Ops IQ automated report</p>
  </div>
</body></html>"""

    def _render_pie_chart_svg(users: list[dict], max_slices: int = 8) -> str:
        """Generate a base64-encoded SVG pie chart for user token distribution.

        Returns an <img> tag with the chart embedded as a data URI — compatible
        with Gmail and most modern email clients without any external hosting.
        """
        import math
        import base64

        COLORS = [
            "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
            "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
            "#9c755f", "#bab0ac",
        ]

        total = sum(u.get("total_tokens", 0) for u in users)
        if total == 0 or not users:
            return ""

        top = list(users[:max_slices])
        rest_tokens = sum(u.get("total_tokens", 0) for u in users[max_slices:])
        if rest_tokens > 0:
            top.append({"user_id": "Others", "total_tokens": rest_tokens,
                        "input_tokens": 0, "output_tokens": 0, "requests": 0})

        total_top = sum(s["total_tokens"] for s in top)
        cx, cy, r = 150, 150, 120
        start = -math.pi / 2

        paths: list[str] = []
        pct_labels: list[str] = []

        for i, s in enumerate(top):
            frac = s["total_tokens"] / total_top
            sweep = 2 * math.pi * frac
            color = COLORS[i % len(COLORS)]

            if len(top) == 1 or frac >= 0.9999:
                # Full circle — arc command cannot draw a complete circle
                paths.append(
                    f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" '
                    f'stroke="#fff" stroke-width="2.5"/>'
                )
                pct_labels.append(
                    f'<text x="{cx}" y="{cy}" text-anchor="middle" '
                    f'dominant-baseline="central" font-size="13" '
                    f'font-weight="bold" fill="#fff">100%</text>'
                )
                start += sweep
                continue

            end = start + sweep
            x1 = cx + r * math.cos(start)
            y1 = cy + r * math.sin(start)
            x2 = cx + r * math.cos(end)
            y2 = cy + r * math.sin(end)
            large = 1 if sweep > math.pi else 0
            d = (f"M {cx},{cy} L {x1:.2f},{y1:.2f} "
                 f"A {r},{r} 0 {large},1 {x2:.2f},{y2:.2f} Z")
            paths.append(
                f'<path d="{d}" fill="{color}" stroke="#fff" stroke-width="2.5"/>'
            )
            if frac > 0.04:
                mid = start + sweep / 2
                lx = cx + r * 0.62 * math.cos(mid)
                ly = cy + r * 0.62 * math.sin(mid)
                pct_labels.append(
                    f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                    f'dominant-baseline="central" font-size="10" '
                    f'font-weight="bold" fill="#fff">{frac * 100:.0f}%</text>'
                )
            start = end

        legend: list[str] = []
        for i, s in enumerate(top):
            frac = s["total_tokens"] / total_top
            name = s["user_id"]
            if "@" in name:
                name = name.split("@")[0]
            if len(name) > 18:
                name = name[:18] + "…"
            tk = s["total_tokens"]
            tk_str = f"{tk / 1_000_000:.2f}M" if tk >= 1_000_000 else f"{tk / 1_000:.1f}k"
            color = COLORS[i % len(COLORS)]
            ly = 30 + i * 24
            legend.append(
                f'<rect x="310" y="{ly}" width="14" height="14" fill="{color}" rx="2"/>'
                f'<text x="330" y="{ly + 11}" font-size="11" fill="#333">'
                f'{name} — {tk_str} ({frac * 100:.0f}%)</text>'
            )

        h = max(320, 30 + len(top) * 24 + 30)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="560" height="{h}">'
            f'<rect width="560" height="{h}" fill="#f8f9fa" rx="8"/>'
            f'<text x="280" y="16" text-anchor="middle" font-size="13" '
            f'font-weight="bold" fill="#333">Daily Token Usage by User</text>'
            + "".join(paths)
            + "".join(pct_labels)
            + "".join(legend)
            + "</svg>"
        )
        b64 = base64.b64encode(svg.encode()).decode()
        return (
            f'<img src="data:image/svg+xml;base64,{b64}" width="560" '
            f'alt="User Token Usage Distribution" '
            f'style="display:block;margin:16px auto;border-radius:8px"/>'
        )

    def _format_user_usage_body(users: list[dict], date_label: str, project: str) -> str:
        total_tokens = sum(u.get("total_tokens", 0) for u in users)
        pie_img = _render_pie_chart_svg(users)

        def _pct(u):
            return f"{u['total_tokens'] / total_tokens * 100:.1f}%" if total_tokens else "0%"

        rows = "".join(
            f"<tr style='background:{'#f8f9fa' if i % 2 == 0 else '#fff'}'>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef'>{i + 1}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef'>{u['user_id']}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"<b>{_fmt_int(u['total_tokens'])}</b></td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"{_fmt_int(u['input_tokens'])}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"{_fmt_int(u['output_tokens'])}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"{_fmt_int(u.get('requests', 0))}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"{_pct(u)}</td>"
            f"</tr>"
            for i, u in enumerate(users[:20])
        )
        more = (
            f"<p style='color:#6c757d;font-size:12px;text-align:center'>"
            f"+ {len(users) - 20} more users not shown</p>"
            if len(users) > 20 else ""
        )
        return f"""<html><body style="font-family:Arial,sans-serif;max-width:720px;margin:auto;color:#212529">
  <div style="background:#6f42c1;padding:20px;border-radius:6px 6px 0 0">
    <h2 style="color:#fff;margin:0">&#128202; Daily User Token Usage &mdash; {project}</h2>
    <p style="color:#e2d9f3;margin:4px 0 0">{date_label} &bull; {len(users)} active user(s) &bull; {_fmt_int(total_tokens)} total tokens</p>
  </div>
  <div style="border:1px solid #dee2e6;border-top:none;padding:20px;border-radius:0 0 6px 6px">
    {pie_img}
    <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:16px">
      <thead><tr style="background:#6f42c1;color:#fff">
        <th style="padding:8px 10px;text-align:left">#</th>
        <th style="padding:8px 10px;text-align:left">User</th>
        <th style="padding:8px 10px;text-align:right">Total Tokens</th>
        <th style="padding:8px 10px;text-align:right">Input</th>
        <th style="padding:8px 10px;text-align:right">Output</th>
        <th style="padding:8px 10px;text-align:right">Requests</th>
        <th style="padding:8px 10px;text-align:right">Share</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    {more}
    <p style="margin-top:14px">
      <a href="https://console.cloud.google.com/firestore?project={project}">View Firestore Usage Data &rarr;</a>
    </p>
    <hr style="border:none;border-top:1px solid #dee2e6;margin:12px 0">
    <p style="color:#6c757d;font-size:11px">Stratova AI &mdash; Ops IQ daily user usage report</p>
  </div>
</body></html>"""

    def check_thresholds(hours: int = 24) -> dict:
        """Check all metrics against configured thresholds and return any violations.

        Does NOT send any emails — purely evaluates current state vs thresholds.
        Can be called interactively via the agent for an instant health check.

        Args:
            hours: Lookback window in hours (1–168). Default 24.

        Returns:
            dict with 'status' (healthy/alert), 'violations' list, and threshold values.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        from tools.google.metrics_tool import get_tools as get_metric_tools
        metric_fns = {fn.__name__: fn for fn in get_metric_tools()}
        thresholds = _get_thresholds()

        violations: list[dict] = []
        metrics: dict = {}

        # Token budget
        token_data = metric_fns["get_token_usage"](hours=hours)
        metrics["tokens"] = token_data
        if token_data.get("status") == "success":
            total = token_data.get("total_tokens", 0)
            budget = thresholds["token_daily_budget"]
            if total > budget:
                violations.append({
                    "check": "Daily Token Budget",
                    "value": f"{total:,}",
                    "threshold": f"{int(budget):,}",
                    "detail": f"Consumed {total / budget * 100:.1f}% of budget",
                })

        # Request budget
        req_data = metric_fns["get_request_counts"](hours=hours)
        metrics["requests"] = req_data
        if req_data.get("status") == "success":
            total_req = req_data.get("total_requests", 0)
            req_budget = thresholds["request_daily_budget"]
            if total_req > req_budget:
                violations.append({
                    "check": "Daily Request Budget",
                    "value": f"{total_req:,}",
                    "threshold": f"{int(req_budget):,}",
                    "detail": f"Consumed {total_req / req_budget * 100:.1f}% of request budget",
                })

        # Error rates — per model
        error_data = metric_fns["get_error_rates"](hours=hours)
        metrics["errors"] = error_data
        if error_data.get("status") == "success":
            err_threshold = thresholds["error_rate_pct"]
            for alert in error_data.get("alerts", []):
                violations.append({
                    "check": f"Error Rate ({alert['model']})",
                    "value": f"{alert['error_rate_pct']}%",
                    "threshold": f"{err_threshold}%",
                    "detail": f"{alert['error_count']} errors / {alert['total_requests']} requests",
                })

        # Latency p99 — per model (skip streaming/live models — their metric is session duration)
        latency_data = metric_fns["get_latency_stats"](hours=hours)
        metrics["latency"] = latency_data
        if latency_data.get("status") == "success":
            lat_threshold = thresholds["latency_p99_ms"]
            for row in latency_data.get("by_model", []):
                model_name = row.get("model", "").lower()
                if any(pat in model_name for pat in _LATENCY_EXCLUDE_PATTERNS):
                    continue  # streaming/live APIs — session duration, not request latency
                p99 = row.get("p99_ms")
                if p99 and p99 > lat_threshold:
                    violations.append({
                        "check": f"Latency p99 ({row['model']})",
                        "value": f"{p99}ms",
                        "threshold": f"{lat_threshold}ms",
                        "detail": f"p50={row.get('p50_ms','?')}ms",
                    })

        # Quota utilisation (when data available)
        quota_data = metric_fns["get_quota_usage_metrics"](hours=1)
        metrics["quota"] = quota_data
        if quota_data.get("status") == "success":
            quota_threshold = thresholds["quota_utilisation_pct"]
            for qa in quota_data.get("alerts", []):
                violations.append({
                    "check": f"Quota {qa['quota_type']} ({qa['model']})",
                    "value": f"{qa['utilisation_pct']}%",
                    "threshold": f"{quota_threshold}%",
                    "detail": f"usage={qa['current_usage']} limit={qa['limit']}",
                })

        logger.info("check_thresholds: violations=%d hours=%d", len(violations), hours)
        return {
            "status": "healthy" if not violations else "alert",
            "violation_count": len(violations),
            "violations": violations,
            "thresholds": thresholds,
            "metrics_window_hours": hours,
            # Full metrics snapshots are included so send_status_report can reuse them
            # without making a second round of API calls.
            "_metrics": metrics,
            "metrics": {
                "token_total": metrics.get("tokens", {}).get("total_tokens"),
                "request_total": metrics.get("requests", {}).get("total_requests"),
                "error_alerts": len(metrics.get("errors", {}).get("alerts", [])),
            },
        }

    def send_alert_email(hours: int = 24) -> dict:
        """Check thresholds and send an alert email via the Email Agent if violations found.

        Uses A2A to call the Laabu Email Agent — no SMTP credentials needed.
        No email is sent when all metrics are within thresholds (safe to call frequently).

        Args:
            hours: Lookback window in hours (1–168). Default 24.

        Returns:
            dict with email dispatch status and violation summary.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        recipients = _get_recipients()
        threshold_result = check_thresholds(hours=hours)
        violations = threshold_result.get("violations", [])

        if not violations:
            return {
                "status": "skipped",
                "message": "All metrics within thresholds — no alert email sent.",
                "health": "healthy",
                "metrics": threshold_result.get("metrics"),
            }

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "GCP")
        subject = f"[Ops IQ Alert] {len(violations)} threshold violation(s) — {project}"
        body = _format_alert_body(violations, hours, project)
        send_result = _dispatch_email(recipients, subject, body)

        return {
            **send_result,
            "violation_count": len(violations),
            "violations": violations,
        }

    def send_status_report(hours: int = 24) -> dict:
        """Send a full platform status report email via the Email Agent.

        Always sends regardless of threshold state — designed for scheduled daily digests.
        Includes: token usage, request counts, error rates, latency, and threshold summary.

        Args:
            hours: Lookback window in hours (1–168). Default 24.

        Returns:
            dict with email dispatch status.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        recipients = _get_recipients()

        # check_thresholds already fetches all metrics — reuse them to avoid double API calls.
        threshold_result = check_thresholds(hours=hours)
        violations = threshold_result.get("violations", [])
        metrics = threshold_result.get("_metrics", {})

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "GCP")
        status_word = "Alert" if violations else "Healthy"
        subject = f"[Ops IQ] Platform Status ({status_word}) — {project}"
        body = _format_report_body(metrics, violations, hours, project)
        send_result = _dispatch_email(recipients, subject, body)

        return {
            **send_result,
            "health": "alert" if violations else "healthy",
            "violation_count": len(violations),
        }

    def _render_agent_bar_chart_svg(agents: list[dict], max_bars: int = 12) -> str:
        """Generate a base64-encoded SVG horizontal bar chart for agent token totals.

        Returns an <img> tag embedded as a data URI.
        """
        import math
        import base64

        COLORS = [
            "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
            "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
        ]

        top = list(agents[:max_bars])
        if not top:
            return ""

        max_tokens = max(a.get("total_tokens", 0) for a in top) or 1
        bar_h = 22
        pad_left = 150
        pad_top = 30
        bar_max_w = 340
        w = 560
        h = pad_top + len(top) * (bar_h + 6) + 30

        bars: list[str] = []
        for i, a in enumerate(top):
            total = a.get("total_tokens", 0)
            bar_w = max(4, int(bar_max_w * total / max_tokens))
            color = COLORS[i % len(COLORS)]
            y = pad_top + i * (bar_h + 6)
            name = a["agent_name"].replace("_agent", "").replace("_", " ").title()
            if len(name) > 20:
                name = name[:20] + "…"
            tk = total
            tk_str = f"{tk / 1_000_000:.2f}M" if tk >= 1_000_000 else f"{tk / 1_000:.1f}k"
            bars.append(
                f'<text x="{pad_left - 6}" y="{y + bar_h // 2 + 4}" '
                f'text-anchor="end" font-size="10" fill="#444">{name}</text>'
                f'<rect x="{pad_left}" y="{y}" width="{bar_w}" height="{bar_h}" '
                f'fill="{color}" rx="3"/>'
                f'<text x="{pad_left + bar_w + 5}" y="{y + bar_h // 2 + 4}" '
                f'font-size="10" fill="#333">{tk_str}</text>'
            )

        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
            f'<rect width="{w}" height="{h}" fill="#f8f9fa" rx="8"/>'
            f'<text x="{w // 2}" y="18" text-anchor="middle" font-size="13" '
            f'font-weight="bold" fill="#333">Token Usage by Agent</text>'
            + "".join(bars)
            + "</svg>"
        )
        b64 = base64.b64encode(svg.encode()).decode()
        return (
            f'<img src="data:image/svg+xml;base64,{b64}" width="{w}" '
            f'alt="Agent Token Usage" '
            f'style="display:block;margin:16px auto;border-radius:8px"/>'
        )

    def _format_agent_usage_body(agents: list[dict], date_label: str, project: str) -> str:
        total_tokens = sum(a.get("total_tokens", 0) for a in agents)
        bar_img = _render_agent_bar_chart_svg(agents)

        rows = "".join(
            f"<tr style='background:{'#f8f9fa' if i % 2 == 0 else '#fff'}'>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef'>{i + 1}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef'>{a['agent_name']}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"<b>{_fmt_int(a['total_tokens'])}</b></td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"{_fmt_int(a['input_tokens'])}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"{_fmt_int(a['output_tokens'])}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"{_fmt_int(a.get('requests', 0))}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"{a.get('unique_users', 0)}</td>"
            f"<td style='padding:7px 10px;border-bottom:1px solid #e9ecef;text-align:right'>"
            f"{a['total_tokens'] / total_tokens * 100:.1f}%</td>"
            f"</tr>"
            for i, a in enumerate(agents)
        )
        return f"""<html><body style="font-family:Arial,sans-serif;max-width:760px;margin:auto;color:#212529">
  <div style="background:#0d6efd;padding:20px;border-radius:6px 6px 0 0">
    <h2 style="color:#fff;margin:0">&#129302; Daily Agent Token Usage &mdash; {project}</h2>
    <p style="color:#cfe2ff;margin:4px 0 0">{date_label} &bull; {len(agents)} active agent(s) &bull; {_fmt_int(total_tokens)} total tokens</p>
  </div>
  <div style="border:1px solid #dee2e6;border-top:none;padding:20px;border-radius:0 0 6px 6px">
    {bar_img}
    <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:16px">
      <thead><tr style="background:#0d6efd;color:#fff">
        <th style="padding:8px 10px;text-align:left">#</th>
        <th style="padding:8px 10px;text-align:left">Agent</th>
        <th style="padding:8px 10px;text-align:right">Total Tokens</th>
        <th style="padding:8px 10px;text-align:right">Input</th>
        <th style="padding:8px 10px;text-align:right">Output</th>
        <th style="padding:8px 10px;text-align:right">Requests</th>
        <th style="padding:8px 10px;text-align:right">Users</th>
        <th style="padding:8px 10px;text-align:right">Share</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p style="margin-top:14px">
      <a href="https://console.cloud.google.com/firestore?project={project}">View Firestore Usage Data &rarr;</a>
    </p>
    <hr style="border:none;border-top:1px solid #dee2e6;margin:12px 0">
    <p style="color:#6c757d;font-size:11px">Stratova AI &mdash; Ops IQ daily agent usage report</p>
  </div>
</body></html>"""

    def send_user_usage_report(days: int = 1) -> dict:
        """Send a daily user-wise token usage report with an inline pie chart via email.

        Queries Firestore for per-user token consumption over the specified window,
        generates an inline SVG pie chart, and dispatches an HTML email to all
        configured recipients. Designed to be called from the daily Cloud Scheduler job
        alongside aggregate_daily_user_usage to both snapshot and notify.

        Args:
            days: Lookback window in days (1–30). Default 1 (yesterday's usage).

        Returns:
            dict with email dispatch status, total_users, and total_tokens.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        from tools.firestore.usage_tracker_tool import get_tools as get_usage_tools
        usage_fns = {fn.__name__: fn for fn in get_usage_tools()}

        days = max(1, min(days, 30))
        usage_data = usage_fns["get_top_users"](days=days, limit=50)

        if usage_data.get("status") in ("no_data", "disabled"):
            return {
                "status": "skipped",
                "message": usage_data.get("message", f"No user usage data in the last {days} day(s)."),
                "total_users": 0,
            }
        if usage_data.get("status") == "error":
            return usage_data

        users = usage_data.get("top_users", [])
        if not users:
            return {"status": "skipped", "message": "No users with token usage found.", "total_users": 0}

        from datetime import timezone as _tz, timedelta as _td
        yesterday = (__import__("datetime").datetime.now(_tz.utc) - _td(days=1)).strftime("%Y-%m-%d")
        date_label = yesterday if days == 1 else f"last {days} days"

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "GCP")
        recipients = _get_recipients()
        subject = f"[Ops IQ] Daily User Token Usage — {date_label} — {project}"
        body = _format_user_usage_body(users, date_label, project)
        send_result = _dispatch_email(recipients, subject, body)

        total_tokens = sum(u.get("total_tokens", 0) for u in users)
        logger.info("send_user_usage_report: date=%s users=%d tokens=%d", date_label, len(users), total_tokens)
        return {
            **send_result,
            "report_date": date_label,
            "total_users": len(users),
            "total_tokens": total_tokens,
        }

    def send_agent_usage_report(days: int = 1) -> dict:
        """Send a daily per-agent token usage report with an inline bar chart via email.

        Queries Firestore for per-agent token consumption over the specified window,
        generates an inline SVG horizontal bar chart, and dispatches an HTML email.

        Args:
            days: Lookback window in days (1–30). Default 1 (yesterday's usage).

        Returns:
            dict with email dispatch status, total_agents, and total_tokens.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        from tools.firestore.usage_tracker_tool import get_tools as get_usage_tools
        usage_fns = {fn.__name__: fn for fn in get_usage_tools()}

        days = max(1, min(days, 30))
        usage_data = usage_fns["get_agent_usage_breakdown"](days=days)

        if usage_data.get("status") in ("no_data", "disabled"):
            return {
                "status": "skipped",
                "message": usage_data.get("message", f"No agent usage data in the last {days} day(s)."),
                "total_agents": 0,
            }
        if usage_data.get("status") == "error":
            return usage_data

        agents = usage_data.get("by_agent", [])
        if not agents:
            return {"status": "skipped", "message": "No agents with token usage found.", "total_agents": 0}

        from datetime import timezone as _tz, timedelta as _td
        yesterday = (__import__("datetime").datetime.now(_tz.utc) - _td(days=1)).strftime("%Y-%m-%d")
        date_label = yesterday if days == 1 else f"last {days} days"

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "GCP")
        recipients = _get_recipients()
        subject = f"[Ops IQ] Daily Agent Token Usage — {date_label} — {project}"
        body = _format_agent_usage_body(agents, date_label, project)
        send_result = _dispatch_email(recipients, subject, body)

        total_tokens = sum(a.get("total_tokens", 0) for a in agents)
        logger.info("send_agent_usage_report: date=%s agents=%d tokens=%d", date_label, len(agents), total_tokens)
        return {
            **send_result,
            "report_date": date_label,
            "total_agents": len(agents),
            "total_tokens": total_tokens,
        }

    def _format_eod_body(
        metrics: dict,
        violations: list[dict],
        agents: list[dict],
        users: list[dict],
        hours: int,
        date_label: str,
        project: str,
    ) -> str:
        """Build the combined end-of-day HTML digest email."""
        status_color = "#dc3545" if violations else "#198754"
        status_badge = (
            f"<span style='background:#dc3545;color:#fff;padding:2px 10px;"
            f"border-radius:12px;font-size:12px;font-weight:bold'>"
            f"&#x26A0; {len(violations)} ALERT(S)</span>"
            if violations else
            "<span style='background:#198754;color:#fff;padding:2px 10px;"
            "border-radius:12px;font-size:12px;font-weight:bold'>&#x2705; HEALTHY</span>"
        )

        tokens_m = metrics.get("tokens", {})
        reqs_m = metrics.get("requests", {})
        errors_m = metrics.get("errors", {})
        latency_m = metrics.get("latency", {})

        # ── Key metric tiles ──────────────────────────────────────────────────
        def _tile(value, label, color="#0d6efd"):
            return (
                f"<div style='flex:1;min-width:120px;padding:12px 8px;"
                f"background:#f8f9fa;border-radius:6px;text-align:center;"
                f"border-top:3px solid {color}'>"
                f"<div style='font-size:20px;font-weight:bold;color:{color}'>{value}</div>"
                f"<div style='font-size:10px;color:#6c757d;margin-top:3px'>{label}</div></div>"
            )

        total_tokens = tokens_m.get("total_tokens") or 0
        total_reqs = reqs_m.get("total_requests") or 0
        error_alerts = len(errors_m.get("alerts", []))
        lat_p99 = "N/A"
        for row in latency_m.get("by_model", []):
            if not any(p in row.get("model", "").lower() for p in _LATENCY_EXCLUDE_PATTERNS):
                v = row.get("p99_ms")
                if v:
                    lat_p99 = f"{v}ms"
                    break

        tiles = (
            _tile(_fmt_int(total_tokens), "Total Tokens")
            + _tile(_fmt_int(total_reqs), "API Requests", "#6f42c1")
            + _tile(str(error_alerts), "Error Alerts", "#dc3545" if error_alerts else "#198754")
            + _tile(lat_p99, "Latency p99", "#fd7e14")
        )

        # ── Violations block ─────────────────────────────────────────────────
        if violations:
            v_rows = "".join(
                f"<tr style='background:#fff3cd'>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #ffc107'><b>{v['check']}</b></td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #ffc107;color:#dc3545'>{v['value']}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #ffc107'>{v['threshold']}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #ffc107'>{v['detail']}</td>"
                f"</tr>"
                for v in violations
            )
            health_block = (
                f"<div style='border-left:4px solid #dc3545;padding:10px 14px;"
                f"background:#fff5f5;border-radius:0 6px 6px 0;margin-bottom:16px'>"
                f"<b style='color:#dc3545'>Threshold Violations</b>"
                f"<table style='width:100%;border-collapse:collapse;font-size:12px;margin-top:8px'>"
                f"<thead><tr style='background:#f8f9fa'>"
                f"<th style='padding:5px 10px;text-align:left'>Check</th>"
                f"<th style='padding:5px 10px;text-align:left'>Value</th>"
                f"<th style='padding:5px 10px;text-align:left'>Threshold</th>"
                f"<th style='padding:5px 10px;text-align:left'>Detail</th>"
                f"</tr></thead><tbody>{v_rows}</tbody></table></div>"
            )
        else:
            health_block = (
                "<div style='border-left:4px solid #198754;padding:10px 14px;"
                "background:#f0fff4;border-radius:0 6px 6px 0;margin-bottom:16px'>"
                "<b style='color:#198754'>&#x2705; All platform metrics are within configured thresholds.</b>"
                "</div>"
            )

        # ── Token usage by model (compact, top 5) ────────────────────────────
        model_rows = "".join(
            f"<tr><td style='padding:4px 8px;border-bottom:1px solid #f0f0f0'>{r['model']}</td>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #f0f0f0;text-align:right'>{_fmt_int(r.get('total_tokens'))}</td>"
            f"<td style='padding:4px 8px;border-bottom:1px solid #f0f0f0;text-align:right'>{_fmt_int(r.get('request_count'))}</td>"
            f"</tr>"
            for r in tokens_m.get("by_model", [])[:5]
        ) or "<tr><td colspan='3' style='padding:6px;color:#6c757d'>No model data</td></tr>"

        # ── Agent table (top 10) ──────────────────────────────────────────────
        agent_total = sum(a.get("total_tokens", 0) for a in agents) or 1
        agent_rows = "".join(
            f"<tr style='background:{'#f8f9fa' if i % 2 == 0 else '#fff'}'>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef'>{i + 1}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef'>{a['agent_name']}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'><b>{_fmt_int(a['total_tokens'])}</b></td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'>{_fmt_int(a['input_tokens'])}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'>{_fmt_int(a['output_tokens'])}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'>{_fmt_int(a.get('requests', 0))}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'>{a.get('unique_users', 0)}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'>{a['total_tokens'] / agent_total * 100:.1f}%</td>"
            f"</tr>"
            for i, a in enumerate(agents[:10])
        ) or "<tr><td colspan='8' style='padding:6px;color:#6c757d'>No agent usage data</td></tr>"

        agent_more = (
            f"<p style='color:#6c757d;font-size:11px;text-align:center'>+ {len(agents) - 10} more agents not shown</p>"
            if len(agents) > 10 else ""
        )

        # ── User table (top 10) ───────────────────────────────────────────────
        user_total = sum(u.get("total_tokens", 0) for u in users) or 1
        user_rows = "".join(
            f"<tr style='background:{'#f8f9fa' if i % 2 == 0 else '#fff'}'>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef'>{i + 1}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef'>{u['user_id']}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'><b>{_fmt_int(u['total_tokens'])}</b></td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'>{_fmt_int(u['input_tokens'])}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'>{_fmt_int(u['output_tokens'])}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'>{_fmt_int(u.get('requests', 0))}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e9ecef;text-align:right'>{u['total_tokens'] / user_total * 100:.1f}%</td>"
            f"</tr>"
            for i, u in enumerate(users[:10])
        ) or "<tr><td colspan='7' style='padding:6px;color:#6c757d'>No user usage data</td></tr>"

        user_more = (
            f"<p style='color:#6c757d;font-size:11px;text-align:center'>+ {len(users) - 10} more users not shown</p>"
            if len(users) > 10 else ""
        )

        bar_img = _render_agent_bar_chart_svg(agents, max_bars=10)
        pie_img = _render_pie_chart_svg(users, max_slices=8)

        def _section(title, icon, color, content):
            return (
                f"<div style='margin-top:24px'>"
                f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:10px'>"
                f"<span style='font-size:16px'>{icon}</span>"
                f"<h3 style='margin:0;font-size:14px;color:{color}'>{title}</h3>"
                f"<div style='flex:1;border-top:1px solid #dee2e6;margin-left:8px'></div>"
                f"</div>{content}</div>"
            )

        health_section = _section("Platform Health", "&#x1F6A6;", status_color, health_block)

        model_section = _section("Token &amp; Request Breakdown by Model", "&#x1F4CA;", "#0d6efd",
            f"<table style='width:100%;border-collapse:collapse;font-size:12px'>"
            f"<thead><tr style='background:#f8f9fa'>"
            f"<th style='padding:5px 8px;text-align:left'>Model</th>"
            f"<th style='padding:5px 8px;text-align:right'>Tokens</th>"
            f"<th style='padding:5px 8px;text-align:right'>Requests</th>"
            f"</tr></thead><tbody>{model_rows}</tbody></table>"
        )

        agent_section = _section("Agent Usage", "&#x1F916;", "#0d6efd",
            bar_img
            + f"<table style='width:100%;border-collapse:collapse;font-size:12px;margin-top:8px'>"
            f"<thead><tr style='background:#0d6efd;color:#fff'>"
            f"<th style='padding:6px 8px;text-align:left'>#</th>"
            f"<th style='padding:6px 8px;text-align:left'>Agent</th>"
            f"<th style='padding:6px 8px;text-align:right'>Total</th>"
            f"<th style='padding:6px 8px;text-align:right'>Input</th>"
            f"<th style='padding:6px 8px;text-align:right'>Output</th>"
            f"<th style='padding:6px 8px;text-align:right'>Reqs</th>"
            f"<th style='padding:6px 8px;text-align:right'>Users</th>"
            f"<th style='padding:6px 8px;text-align:right'>Share</th>"
            f"</tr></thead><tbody>{agent_rows}</tbody></table>{agent_more}"
        )

        user_section = _section("User Usage", "&#x1F464;", "#6f42c1",
            pie_img
            + f"<table style='width:100%;border-collapse:collapse;font-size:12px;margin-top:8px'>"
            f"<thead><tr style='background:#6f42c1;color:#fff'>"
            f"<th style='padding:6px 8px;text-align:left'>#</th>"
            f"<th style='padding:6px 8px;text-align:left'>User</th>"
            f"<th style='padding:6px 8px;text-align:right'>Total</th>"
            f"<th style='padding:6px 8px;text-align:right'>Input</th>"
            f"<th style='padding:6px 8px;text-align:right'>Output</th>"
            f"<th style='padding:6px 8px;text-align:right'>Reqs</th>"
            f"<th style='padding:6px 8px;text-align:right'>Share</th>"
            f"</tr></thead><tbody>{user_rows}</tbody></table>{user_more}"
        )

        return f"""<html><body style="font-family:Arial,sans-serif;max-width:760px;margin:auto;color:#212529">
  <div style="background:linear-gradient(135deg,#0d6efd,#6f42c1);padding:24px;border-radius:6px 6px 0 0">
    <table style="width:100%;border-collapse:collapse">
      <tr>
        <td>
          <h2 style="color:#fff;margin:0;font-size:20px">&#x1F4CB; End of Day Summary &mdash; {project}</h2>
          <p style="color:#cfe2ff;margin:4px 0 0">{date_label} &bull; last {hours}h window</p>
        </td>
        <td style="text-align:right;vertical-align:top">{status_badge}</td>
      </tr>
    </table>
  </div>
  <div style="border:1px solid #dee2e6;border-top:none;padding:20px 24px;border-radius:0 0 6px 6px">

    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px">
      {tiles}
    </div>

    {health_section}
    {model_section}
    {agent_section}
    {user_section}

    <div style="margin-top:20px;display:flex;gap:16px;flex-wrap:wrap">
      <a href="https://console.cloud.google.com/monitoring?project={project}"
         style="font-size:12px;color:#0d6efd">Cloud Monitoring &rarr;</a>
      <a href="https://console.cloud.google.com/firestore?project={project}"
         style="font-size:12px;color:#0d6efd">Firestore Usage Data &rarr;</a>
    </div>
    <hr style="border:none;border-top:1px solid #dee2e6;margin:16px 0">
    <p style="color:#6c757d;font-size:11px;margin:0">
      Stratova AI &mdash; Ops IQ automated EOD report &bull; Generated daily at 23:55 UTC
    </p>
  </div>
</body></html>"""

    def send_eod_summary(hours: int = 24) -> dict:
        """Send a combined end-of-day digest with all monitoring metrics and usage data.

        A single email that replaces running --report, --user-report, and --agent-report
        separately. Includes:
          - Overall platform health status and threshold violations
          - Key metric tiles (tokens, requests, errors, latency p99)
          - Token & request breakdown by model
          - Agent usage bar chart + table (top 10 agents by token consumption)
          - User usage pie chart + table (top 10 users by token consumption)

        Also snapshots both daily_user_usage and daily_agent_usage to Firestore
        before sending so historical lookups work without separate jobs.

        Args:
            hours: Lookback window for monitoring metrics (default 24 = today).

        Returns:
            dict with email dispatch status and summary counts.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        from tools.firestore.usage_tracker_tool import get_tools as get_usage_tools
        usage_fns = {fn.__name__: fn for fn in get_usage_tools()}

        # 1. Fetch monitoring metrics (check_thresholds calls all Cloud Monitoring APIs)
        threshold_result = check_thresholds(hours=hours)
        violations = threshold_result.get("violations", [])
        metrics = threshold_result.get("_metrics", {})

        # 2. Snapshot both dimensions to Firestore (best-effort — don't fail the email)
        try:
            usage_fns["aggregate_daily_user_usage"]()
        except Exception as exc:
            logger.debug("EOD: user snapshot failed (non-fatal): %s", exc)
        try:
            usage_fns["aggregate_daily_agent_usage"]()
        except Exception as exc:
            logger.debug("EOD: agent snapshot failed (non-fatal): %s", exc)

        # 3. Fetch usage data (fresh scan — snapshots above are for history only)
        agent_data = usage_fns["get_agent_usage_breakdown"](days=1)
        agents = agent_data.get("by_agent", []) if agent_data.get("status") == "success" else []

        user_data = usage_fns["get_top_users"](days=1, limit=50)
        users = user_data.get("top_users", []) if user_data.get("status") == "success" else []

        from datetime import timezone as _tz, timedelta as _td
        yesterday = (__import__("datetime").datetime.now(_tz.utc) - _td(days=1)).strftime("%Y-%m-%d")
        date_label = yesterday

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "GCP")
        recipients = _get_recipients()
        status_word = "Alert" if violations else "Healthy"
        subject = f"[Ops IQ] EOD Summary ({status_word}) — {date_label} — {project}"
        body = _format_eod_body(metrics, violations, agents, users, hours, date_label, project)
        send_result = _dispatch_email(recipients, subject, body)

        total_agent_tokens = sum(a.get("total_tokens", 0) for a in agents)
        total_user_tokens = sum(u.get("total_tokens", 0) for u in users)
        logger.info(
            "send_eod_summary: date=%s violations=%d agents=%d users=%d",
            date_label, len(violations), len(agents), len(users),
        )
        return {
            **send_result,
            "report_date": date_label,
            "health": "alert" if violations else "healthy",
            "violation_count": len(violations),
            "total_agents": len(agents),
            "total_agent_tokens": total_agent_tokens,
            "total_users": len(users),
            "total_user_tokens": total_user_tokens,
        }

    return [check_thresholds, send_alert_email, send_status_report, send_user_usage_report, send_agent_usage_report, send_eod_summary]
