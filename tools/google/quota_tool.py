"""Quota monitoring tools using the Cloud Quotas API (cloudquotas_v1).

Surfaces quota limits and preferences for GCP services — primarily
aiplatform.googleapis.com — so Ops IQ can report headroom before hitting
rate limits on Vertex AI / Gemini inference.

IAM required: roles/serviceusage.serviceUsageViewer
"""
from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)

_AIPLATFORM_SERVICE = "aiplatform.googleapis.com"

# Human-readable labels for the most relevant quota metrics
_QUOTA_LABELS: dict[str, str] = {
    "online_prediction_requests_per_base_model": "Online Prediction Requests / Base Model",
    "generate_content_requests_per_minute_per_project_per_base_model": "Generate Content RPM / Model",
    "generate_content_requests_per_minute_per_project_per_region_per_base_model": "Generate Content RPM / Region / Model",
    "online_prediction_requests": "Online Prediction Requests (generic)",
    "custom_model_training_cpus": "Training CPUs",
    "custom_model_serving_prediction_nodes_per_region": "Prediction Nodes / Region",
}


def get_tools() -> list[Callable]:
    from config import get_config

    def _check_enabled() -> dict | None:
        cfg = get_config()
        tc = cfg.tools.get("quota_monitoring")
        if not tc or not tc.enabled:
            return {"status": "disabled", "message": "Quota monitoring is currently disabled."}
        return None

    def _project() -> str:
        cfg = get_config()
        tc = cfg.tools.get("quota_monitoring")
        if tc:
            p = tc.config.get("project", "")
            if p:
                return p
        return os.environ.get("GOOGLE_CLOUD_PROJECT", "")

    def _services() -> list[str]:
        cfg = get_config()
        tc = cfg.tools.get("quota_monitoring")
        if tc:
            return tc.config.get("services", [_AIPLATFORM_SERVICE])
        return [_AIPLATFORM_SERVICE]

    def list_vertex_quotas(service: str = "aiplatform.googleapis.com") -> dict:
        """List all quota limits for a GCP service (default: aiplatform.googleapis.com).

        Returns quota_id, metric name, current limit, unit, and a human-readable
        label for each quota. Useful for understanding capacity before hitting limits.

        Args:
            service: GCP service name (e.g. "aiplatform.googleapis.com").
                     Defaults to Vertex AI.

        Returns:
            dict with status, service, quota list (quota_id, metric, limit, unit, label).
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        project = _project()
        if not project:
            return {"status": "error", "message": "GCP project is not configured."}

        try:
            from google.cloud import cloudquotas_v1

            client = cloudquotas_v1.CloudQuotasClient()
            parent = f"projects/{project}/locations/global/services/{service}"

            quotas = []
            request = cloudquotas_v1.ListQuotaInfosRequest(parent=parent)
            page = client.list_quota_infos(request=request)

            count = 0
            for quota_info in page:
                if count >= 100:
                    break
                metric = quota_info.metric or ""
                metric_short = metric.split("/")[-1] if "/" in metric else metric
                limit_val = None
                unit = ""
                if quota_info.quota_infos:
                    first = quota_info.quota_infos[0]
                    limit_val = getattr(first, "value", None)
                    unit = getattr(quota_info, "unit", "") or ""

                quotas.append({
                    "quota_id": quota_info.name,
                    "metric": metric,
                    "metric_short": metric_short,
                    "limit": limit_val,
                    "unit": unit,
                    "label": _QUOTA_LABELS.get(metric_short, metric_short.replace("_", " ").title()),
                    "is_fixed": getattr(quota_info, "is_fixed", False),
                    "is_concurrent": getattr(quota_info, "is_concurrent", False),
                })
                count += 1

            logger.info("list_vertex_quotas: service=%s count=%d", service, len(quotas))
            return {
                "status": "success",
                "service": service,
                "project": project,
                "quota_count": len(quotas),
                "quotas": quotas,
                "note": "Limit values shown are currently granted limits. Use get_quota_preferences() to see requested increases.",
            }
        except Exception as exc:
            err = str(exc)
            logger.error("list_vertex_quotas error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {
                    "status": "error",
                    "message": "Permission denied reading quota information. Ensure roles/serviceusage.serviceUsageViewer is granted.",
                }
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                return {"status": "error", "message": "Quota API rate limited. Please wait 30 seconds and retry."}
            return {"status": "error", "message": "Unable to retrieve quota information. Please try again shortly."}

    def get_quota_preferences(service: str = "aiplatform.googleapis.com") -> dict:
        """List all quota preferences (requested increases) for a service.

        Shows current quota adjustment requests — pending, granted, or denied.
        Useful for tracking quota increase requests submitted to Google.

        Args:
            service: GCP service name. Defaults to aiplatform.googleapis.com.

        Returns:
            dict with list of quota preferences including state and justification.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        project = _project()
        if not project:
            return {"status": "error", "message": "GCP project is not configured."}

        try:
            from google.cloud import cloudquotas_v1

            client = cloudquotas_v1.CloudQuotasClient()
            parent = f"projects/{project}/locations/global"

            preferences = []
            request = cloudquotas_v1.ListQuotaPreferencesRequest(
                parent=parent,
                filter=f'service="{service}"',
            )
            for pref in client.list_quota_preferences(request=request):
                metric = getattr(pref, "quota_id", "") or ""
                preferences.append({
                    "name": pref.name,
                    "service": getattr(pref, "service", service),
                    "quota_id": metric,
                    "preferred_value": getattr(pref, "quota_config", {}).get("preferred_value") if hasattr(pref, "quota_config") else None,
                    "state": str(getattr(getattr(pref, "quota_config", None), "state", "UNKNOWN")),
                    "justification": getattr(getattr(pref, "quota_config", None), "justification", ""),
                    "update_time": str(getattr(pref, "update_time", "")),
                })

            logger.info("get_quota_preferences: service=%s count=%d", service, len(preferences))
            return {
                "status": "success",
                "service": service,
                "project": project,
                "preference_count": len(preferences),
                "preferences": preferences,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_quota_preferences error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {
                    "status": "error",
                    "message": "Permission denied reading quota preferences. Ensure roles/serviceusage.serviceUsageViewer is granted.",
                }
            return {"status": "error", "message": "Unable to retrieve quota preferences. Please try again shortly."}

    def get_vertex_quota_summary() -> dict:
        """Return a concise quota headroom summary for the most critical Vertex AI quotas.

        Queries the top generative AI quotas and flags any that are fixed (cannot
        be increased) or likely to be a bottleneck. This is the recommended starting
        point for understanding your quota situation.

        Returns:
            dict with critical_quotas list and any warnings about low headroom.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        result = list_vertex_quotas(service=_AIPLATFORM_SERVICE)
        if result.get("status") != "success":
            return result

        critical_keywords = [
            "generate_content", "online_prediction", "online_serving",
            "base_model", "requests_per_minute",
        ]
        critical = [
            q for q in result.get("quotas", [])
            if any(kw in q.get("metric", "").lower() for kw in critical_keywords)
        ]

        warnings = []
        for q in critical:
            if q.get("is_fixed"):
                warnings.append(f"'{q['label']}' is a fixed quota — cannot be increased via quota requests.")

        logger.info("get_vertex_quota_summary: critical=%d warnings=%d", len(critical), len(warnings))
        return {
            "status": "success",
            "project": result["project"],
            "critical_quota_count": len(critical),
            "critical_quotas": critical,
            "warnings": warnings,
            "note": "Fixed quotas cannot be raised via the Quotas console. Contact Google Cloud support for exceptions.",
        }

    return [
        list_vertex_quotas,
        get_quota_preferences,
        get_vertex_quota_summary,
    ]
