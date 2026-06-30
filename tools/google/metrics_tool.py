"""Cloud Monitoring time-series tools for LLM and Vertex AI usage metrics.

Reads token counts, request rates, latency, and error rates from Cloud Monitoring
using the verified metric names for this project.

IAM required: roles/monitoring.viewer

Verified metrics (confirmed available in project):
  - aiplatform.googleapis.com/publisher/online_serving/token_count
      labels: type=input|output, resource.model_user_id=<model>
  - aiplatform.googleapis.com/publisher/online_serving/model_invocation_count
      labels: response_code
  - aiplatform.googleapis.com/publisher/online_serving/first_token_latencies
  - aiplatform.googleapis.com/publisher/online_serving/model_invocation_latencies
  - aiplatform.googleapis.com/prediction/online/prediction_count  (Agent Engines)
  - aiplatform.googleapis.com/quota/*/usage and /limit  (quota via Cloud Monitoring)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable

logger = logging.getLogger(__name__)

_MAX_LOOKBACK_HOURS = 168  # 7 days
_TOP_N = 10


def get_tools() -> list[Callable]:
    from config import get_config

    def _check_enabled() -> dict | None:
        cfg = get_config()
        tc = cfg.tools.get("metrics_monitoring")
        if not tc or not tc.enabled:
            return {"status": "disabled", "message": "Metrics monitoring is currently disabled."}
        return None

    def _project() -> str:
        return os.environ.get("GOOGLE_CLOUD_PROJECT", "")

    def _clamp_hours(hours: int) -> int:
        cfg = get_config()
        tc = cfg.tools.get("metrics_monitoring")
        max_h = tc.config.get("max_lookback_hours", _MAX_LOOKBACK_HOURS) if tc else _MAX_LOOKBACK_HOURS
        return max(1, min(hours, int(max_h)))

    def _build_interval(hours: int):
        from google.cloud import monitoring_v3

        end_secs = int(time.time())
        start_secs = end_secs - (hours * 3600)
        return monitoring_v3.TimeInterval(
            end_time={"seconds": end_secs},
            start_time={"seconds": start_secs},
        ), start_secs, end_secs

    def _fetch_series(project: str, metric_type: str, hours: int,
                      extra_filter: str = "", alignment_period_secs: int = 3600) -> list:
        """Fetch all time series for a metric, summed per model over the window."""
        from google.cloud import monitoring_v3

        client = monitoring_v3.MetricServiceClient()
        interval, start_s, end_s = _build_interval(hours)
        flt = f'metric.type = "{metric_type}"'
        if extra_filter:
            flt = f'{flt} AND {extra_filter}'

        agg = monitoring_v3.Aggregation(
            alignment_period={"seconds": alignment_period_secs},
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
        )
        return list(client.list_time_series(request={
            "name": f"projects/{project}",
            "filter": flt,
            "interval": interval,
            "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            "aggregation": agg,
        })), start_s, end_s

    def _sum_series(series_list: list) -> dict[str, dict]:
        """Aggregate time series by model_user_id, returning {model: {total, points}}."""
        by_model: dict[str, dict] = {}
        for ts in series_list:
            model = ""
            if ts.resource and ts.resource.labels:
                model = ts.resource.labels.get("model_user_id", "") or ts.resource.labels.get("model", "")
            if not model:
                model = "unknown"
            total = sum(
                p.value.int64_value or int(p.value.double_value or 0)
                for p in ts.points
            )
            by_model.setdefault(model, {"model": model, "total": 0, "point_count": 0})
            by_model[model]["total"] += total
            by_model[model]["point_count"] += len(ts.points)
        return by_model

    def get_token_usage(model: str = "", hours: int = 24) -> dict:
        """Return input and output token counts broken down by model.

        Uses the 'token_count' metric with metric.labels.type to split
        input vs output tokens per model.

        Args:
            model: Optional model filter (e.g. "gemini-2.5-flash"). Empty = all models.
            hours: Lookback window in hours (1–168). Default 24.

        Returns:
            dict with input_tokens, output_tokens, total_tokens per model.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        project = _project()
        if not project:
            return {"status": "error", "message": "GCP project is not configured."}

        hours = _clamp_hours(hours)
        model_filter = f'resource.labels.model_user_id = "{model}"' if model else ""

        try:
            input_filter = 'metric.labels.type = "input"'
            if model_filter:
                input_filter = f'{input_filter} AND {model_filter}'
            output_filter = 'metric.labels.type = "output"'
            if model_filter:
                output_filter = f'{output_filter} AND {model_filter}'

            metric = "aiplatform.googleapis.com/publisher/online_serving/token_count"
            inp_series, start_s, end_s = _fetch_series(project, metric, hours, input_filter)
            out_series, _, _ = _fetch_series(project, metric, hours, output_filter)

            if not inp_series and not out_series:
                return {
                    "status": "no_data",
                    "message": f"No token usage data in the last {hours} hours" + (f" for '{model}'" if model else "") + ".",
                    "hours": hours,
                }

            inp_by_model = _sum_series(inp_series)
            out_by_model = _sum_series(out_series)
            all_models = set(inp_by_model) | set(out_by_model)

            rows = []
            for m in all_models:
                inp = inp_by_model.get(m, {}).get("total", 0)
                out = out_by_model.get(m, {}).get("total", 0)
                rows.append({"model": m, "input_tokens": inp, "output_tokens": out, "total_tokens": inp + out})
            rows.sort(key=lambda x: x["total_tokens"], reverse=True)

            grand_in = sum(r["input_tokens"] for r in rows)
            grand_out = sum(r["output_tokens"] for r in rows)

            logger.info("get_token_usage: hours=%d models=%d total=%d", hours, len(rows), grand_in + grand_out)
            return {
                "status": "success",
                "hours": hours,
                "model_filter": model or "all",
                "total_input_tokens": grand_in,
                "total_output_tokens": grand_out,
                "total_tokens": grand_in + grand_out,
                "by_model": rows[:_TOP_N],
                "truncated": len(rows) > _TOP_N,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_token_usage error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading metrics. Ensure roles/monitoring.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve token usage metrics. Please try again shortly."}

    def get_request_counts(hours: int = 24) -> dict:
        """Return request (model invocation) counts per model for the specified window.

        Uses model_invocation_count which covers all Gemini API calls on Vertex AI.

        Args:
            hours: Lookback window in hours (1–168). Default 24.

        Returns:
            dict with total requests and per-model breakdown.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        project = _project()
        if not project:
            return {"status": "error", "message": "GCP project is not configured."}

        hours = _clamp_hours(hours)

        try:
            metric = "aiplatform.googleapis.com/publisher/online_serving/model_invocation_count"
            series, start_s, end_s = _fetch_series(project, metric, hours)
            by_model = _sum_series(series)

            if not by_model:
                return {"status": "no_data", "message": f"No request data in the last {hours} hours.", "hours": hours}

            rows = sorted(by_model.values(), key=lambda x: x["total"], reverse=True)
            for r in rows:
                r["request_count"] = r.pop("total")

            logger.info("get_request_counts: hours=%d total=%d", hours, sum(r["request_count"] for r in rows))
            return {
                "status": "success",
                "hours": hours,
                "total_requests": sum(r["request_count"] for r in rows),
                "by_model": rows[:_TOP_N],
                "truncated": len(rows) > _TOP_N,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_request_counts error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading metrics. Ensure roles/monitoring.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve request count metrics. Please try again shortly."}

    def get_latency_stats(model: str = "", hours: int = 24) -> dict:
        """Return model invocation latency statistics per model.

        Uses model_invocation_latencies which measures end-to-end server-side
        request duration in milliseconds.

        Args:
            model: Optional model filter. Empty = all models.
            hours: Lookback window in hours (1–168). Default 24.

        Returns:
            dict with per-model average latency in milliseconds.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        project = _project()
        if not project:
            return {"status": "error", "message": "GCP project is not configured."}

        hours = _clamp_hours(hours)
        model_filter = f'resource.labels.model_user_id = "{model}"' if model else ""

        try:
            from google.cloud import monitoring_v3

            client = monitoring_v3.MetricServiceClient()
            interval, start_s, end_s = _build_interval(hours)
            metric = "aiplatform.googleapis.com/publisher/online_serving/model_invocation_latencies"
            flt = f'metric.type = "{metric}"'
            if model_filter:
                flt = f'{flt} AND {model_filter}'

            agg = monitoring_v3.Aggregation(
                alignment_period={"seconds": 3600},
                per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_PERCENTILE_99,
            )
            series_p99 = list(client.list_time_series(request={
                "name": f"projects/{project}",
                "filter": flt,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                "aggregation": agg,
            }))
            agg50 = monitoring_v3.Aggregation(
                alignment_period={"seconds": 3600},
                per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_PERCENTILE_50,
            )
            series_p50 = list(client.list_time_series(request={
                "name": f"projects/{project}",
                "filter": flt,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                "aggregation": agg50,
            }))

            if not series_p99 and not series_p50:
                return {"status": "no_data", "message": f"No latency data in the last {hours} hours.", "hours": hours}

            def _avg(series):
                by_model = {}
                for ts in series:
                    m = ts.resource.labels.get("model_user_id", "unknown") if ts.resource else "unknown"
                    vals = [p.value.double_value or p.value.int64_value for p in ts.points if (p.value.double_value or p.value.int64_value)]
                    by_model[m] = round(sum(vals) / len(vals), 1) if vals else None
                return by_model

            p50 = _avg(series_p50)
            p99 = _avg(series_p99)
            all_models = set(p50) | set(p99)

            rows = [{"model": m, "p50_ms": p50.get(m), "p99_ms": p99.get(m)} for m in all_models]
            rows.sort(key=lambda x: x.get("p99_ms") or 0, reverse=True)

            logger.info("get_latency_stats: hours=%d models=%d", hours, len(rows))
            return {
                "status": "success",
                "hours": hours,
                "model_filter": model or "all",
                "latency_unit": "milliseconds",
                "note": "p50/p99 are averaged across hourly alignment periods in the window.",
                "by_model": rows[:_TOP_N],
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_latency_stats error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading metrics. Ensure roles/monitoring.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve latency metrics. Please try again shortly."}

    def get_error_rates(hours: int = 24) -> dict:
        """Return error rates for Vertex AI model invocations.

        Splits model_invocation_count by response_code to compute error rate.
        Alerts on models with error_rate > 1%.

        Args:
            hours: Lookback window in hours (1–168). Default 24.

        Returns:
            dict with error_count, total_count, error_rate_pct per model.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        project = _project()
        if not project:
            return {"status": "error", "message": "GCP project is not configured."}

        hours = _clamp_hours(hours)

        try:
            metric = "aiplatform.googleapis.com/publisher/online_serving/model_invocation_count"
            all_series, _, _ = _fetch_series(project, metric, hours)
            err_series, _, _ = _fetch_series(
                project, metric, hours,
                extra_filter='metric.labels.response_code != "200"',
            )

            if not all_series:
                return {"status": "no_data", "message": f"No request data in the last {hours} hours.", "hours": hours}

            total_map = {m: d["total"] for m, d in _sum_series(all_series).items()}
            error_map = {m: d["total"] for m, d in _sum_series(err_series).items()}

            rows = []
            for m, total in total_map.items():
                errors = error_map.get(m, 0)
                rate = round(errors / total * 100, 2) if total > 0 else 0.0
                rows.append({"model": m, "total_requests": total, "error_count": errors,
                              "error_rate_pct": rate, "alert": rate > 1.0})
            rows.sort(key=lambda x: x["error_rate_pct"], reverse=True)

            logger.info("get_error_rates: hours=%d models=%d alerts=%d", hours, len(rows), sum(1 for r in rows if r["alert"]))
            return {
                "status": "success",
                "hours": hours,
                "alerts": [r for r in rows if r["alert"]],
                "by_model": rows[:_TOP_N],
                "note": "alert=true when error_rate_pct > 1.0%",
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_error_rates error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading metrics. Ensure roles/monitoring.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve error rate metrics. Please try again shortly."}

    def get_quota_usage_metrics(hours: int = 1) -> dict:
        """Return real-time quota usage and limits from Cloud Monitoring.

        Reads aiplatform.googleapis.com/quota/*/usage and /limit metrics which are
        available without enabling the Cloud Quotas API. Shows current consumption
        vs granted limit for input tokens, output tokens, and request quotas per model.

        Args:
            hours: Lookback window in hours (1–24). Default 1 (most recent data).

        Returns:
            dict with per-quota usage, limit, and utilisation percentage.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        project = _project()
        if not project:
            return {"status": "error", "message": "GCP project is not configured."}

        hours = max(1, min(hours, 24))

        # Verified names from list_metric_descriptors; generate_content_* are the active quotas.
        # online_prediction_* quota metrics exist as descriptors but have no time-series data.
        quota_pairs = [
            ("input_tokens_per_min", "aiplatform.googleapis.com/quota/generate_content_input_tokens_per_minute_per_base_model"),
            ("requests_per_min", "aiplatform.googleapis.com/quota/generate_content_requests_per_minute_per_project_per_base_model"),
        ]

        try:
            from google.cloud import monitoring_v3

            client = monitoring_v3.MetricServiceClient()
            interval, start_s, end_s = _build_interval(hours)
            agg = monitoring_v3.Aggregation(
                alignment_period={"seconds": 60},
                per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_MAX,
            )

            results = []
            for quota_name, base_metric in quota_pairs:
                usage_series = list(client.list_time_series(request={
                    "name": f"projects/{project}",
                    "filter": f'metric.type = "{base_metric}/usage"',
                    "interval": interval,
                    "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                    "aggregation": agg,
                }))
                limit_series = list(client.list_time_series(request={
                    "name": f"projects/{project}",
                    "filter": f'metric.type = "{base_metric}/limit"',
                    "interval": interval,
                    "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                    "aggregation": agg,
                }))

                # Index limit by base_model label
                limit_map: dict[str, float] = {}
                for ts in limit_series:
                    model_label = ts.metric.labels.get("base_model", "unknown") if ts.metric else "unknown"
                    max_val = max((p.value.int64_value or p.value.double_value or 0 for p in ts.points), default=0)
                    limit_map[model_label] = max_val

                for ts in usage_series:
                    model_label = ts.metric.labels.get("base_model", "unknown") if ts.metric else "unknown"
                    max_usage = max((p.value.int64_value or p.value.double_value or 0 for p in ts.points), default=0)
                    limit_val = limit_map.get(model_label, 0)
                    util_pct = round(max_usage / limit_val * 100, 1) if limit_val > 0 else None

                    results.append({
                        "quota_type": quota_name,
                        "model": model_label,
                        "current_usage": max_usage,
                        "limit": limit_val,
                        "utilisation_pct": util_pct,
                        "alert": util_pct is not None and util_pct > 80,
                    })

            if not results:
                # Quota metrics only emit data when actively consumed (near the limit).
                # Absence of data means usage is comfortably below quota limits.
                return {
                    "status": "no_data",
                    "message": (
                        "No quota usage data in Cloud Monitoring for the last hour. "
                        "This typically means usage is well below quota limits — GCP only "
                        "emits quota time-series when consumption is significant. "
                        "Current token consumption (last 24h): see get_token_usage tool. "
                        "To view quota limits, use the Cloud Console quota page or enable "
                        "cloudquotas.googleapis.com and retry."
                    ),
                    "hours": hours,
                }

            results.sort(key=lambda x: x.get("utilisation_pct") or 0, reverse=True)
            alerts = [r for r in results if r.get("alert")]

            logger.info("get_quota_usage_metrics: quotas=%d alerts=%d", len(results), len(alerts))
            return {
                "status": "success",
                "hours": hours,
                "quota_count": len(results),
                "alerts": alerts,
                "quotas": results,
                "note": "alert=true when utilisation_pct > 80%. Usage is the per-minute peak in the window.",
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_quota_usage_metrics error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading quota metrics. Ensure roles/monitoring.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve quota usage metrics. Please try again shortly."}

    def get_agent_engine_metrics(hours: int = 24) -> dict:
        """Return request counts for Vertex AI Agent Engine endpoints.

        Uses prediction/online/prediction_count which covers Agent Engine calls.

        Args:
            hours: Lookback window in hours (1–168). Default 24.

        Returns:
            dict with per-endpoint request counts.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        project = _project()
        if not project:
            return {"status": "error", "message": "GCP project is not configured."}

        hours = _clamp_hours(hours)

        try:
            series, start_s, end_s = _fetch_series(
                project,
                "aiplatform.googleapis.com/prediction/online/prediction_count",
                hours,
            )

            if not series:
                return {"status": "no_data", "message": f"No Agent Engine traffic in the last {hours} hours.", "hours": hours}

            endpoints = []
            for ts in series:
                endpoint_id = ts.resource.labels.get("endpoint_id", "unknown") if ts.resource else "unknown"
                total = sum(p.value.int64_value or int(p.value.double_value or 0) for p in ts.points)
                endpoints.append({"endpoint_id": endpoint_id, "total_requests": total})

            endpoints.sort(key=lambda x: x["total_requests"], reverse=True)

            logger.info("get_agent_engine_metrics: hours=%d endpoints=%d", hours, len(endpoints))
            return {
                "status": "success",
                "hours": hours,
                "total_requests": sum(e["total_requests"] for e in endpoints),
                "endpoint_count": len(endpoints),
                "by_endpoint": endpoints[:_TOP_N],
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_agent_engine_metrics error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied reading metrics. Ensure roles/monitoring.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve Agent Engine metrics. Please try again shortly."}

    def get_platform_metrics_summary(hours: int = 24) -> dict:
        """Return a combined summary: tokens, requests, quota usage, and errors.

        Single-call overview for platform health reports.

        Args:
            hours: Lookback window in hours (1–168). Default 24.

        Returns:
            dict with tokens, requests, quota, and error sections.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        token_data = get_token_usage(hours=hours)
        request_data = get_request_counts(hours=hours)
        error_data = get_error_rates(hours=hours)
        quota_data = get_quota_usage_metrics(hours=min(hours, 1))

        anomalies = []
        if error_data.get("status") == "success":
            for a in error_data.get("alerts", []):
                anomalies.append(f"High error rate on '{a['model']}': {a['error_rate_pct']}%")
        if quota_data.get("status") == "success":
            for a in quota_data.get("alerts", []):
                anomalies.append(f"Quota alert: {a['quota_type']} for '{a['model']}' at {a['utilisation_pct']}% utilisation")

        return {
            "status": "success",
            "hours": hours,
            "anomalies_detected": anomalies,
            "tokens": {
                "total_input": token_data.get("total_input_tokens") if token_data.get("status") == "success" else None,
                "total_output": token_data.get("total_output_tokens") if token_data.get("status") == "success" else None,
                "status": token_data.get("status"),
            },
            "requests": {
                "total": request_data.get("total_requests") if request_data.get("status") == "success" else None,
                "status": request_data.get("status"),
            },
            "quota": {
                "alert_count": len(quota_data.get("alerts", [])) if quota_data.get("status") == "success" else None,
                "status": quota_data.get("status"),
            },
            "errors": {
                "alert_count": len(error_data.get("alerts", [])) if error_data.get("status") == "success" else None,
                "status": error_data.get("status"),
            },
            "note": f"Window: last {hours} hours. Call individual tools for per-model breakdowns.",
        }

    return [
        get_token_usage,
        get_request_counts,
        get_latency_stats,
        get_error_rates,
        get_quota_usage_metrics,
        get_agent_engine_metrics,
        get_platform_metrics_summary,
    ]
