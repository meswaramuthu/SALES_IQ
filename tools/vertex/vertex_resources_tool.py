"""Vertex AI resource inventory tools.

Lists and describes deployed Vertex AI resources:
  - Agent Engines (Reasoning Engines / AdkApp deployments)
  - Online prediction endpoints
  - Deployed models per endpoint

IAM required: roles/aiplatform.viewer
"""
from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)


def get_tools() -> list[Callable]:
    from config import get_config

    def _check_enabled() -> dict | None:
        cfg = get_config()
        tc = cfg.tools.get("vertex_resources")
        if not tc or not tc.enabled:
            return {"status": "disabled", "message": "Vertex AI resource monitoring is currently disabled."}
        return None

    def _init_vertexai() -> None:
        import vertexai

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        vertexai.init(project=project, location=location)

    def list_agent_engines(page_size: int = 50) -> dict:
        """List all Vertex AI Agent Engine (Reasoning Engine) deployments.

        Returns metadata for each engine: resource name, display name, state,
        creation and last update timestamps. Does not invoke any agent (no
        cold-start billing).

        Args:
            page_size: Maximum engines to return (1–100). Default 50.

        Returns:
            dict with list of agent engine summaries.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        try:
            _init_vertexai()
            from vertexai import agent_engines

            page_size = max(1, min(page_size, 100))
            engines = []
            for engine in agent_engines.list():
                engines.append({
                    "resource_name": engine.resource_name,
                    "display_name": getattr(engine, "display_name", ""),
                    "state": str(getattr(engine, "state", "UNKNOWN")),
                    "create_time": str(getattr(engine, "create_time", "")),
                    "update_time": str(getattr(engine, "update_time", "")),
                })
                if len(engines) >= page_size:
                    break

            logger.info("list_agent_engines: count=%d", len(engines))
            return {
                "status": "success",
                "count": len(engines),
                "engines": engines,
                "note": "State values: ACTIVE (serving), CREATING, UPDATING, DELETING, FAILED.",
            }
        except Exception as exc:
            err = str(exc)
            logger.error("list_agent_engines error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied listing Agent Engines. Ensure roles/aiplatform.viewer is granted."}
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                return {"status": "error", "message": "Vertex AI API rate limited. Please wait 30 seconds and retry."}
            return {"status": "error", "message": "Unable to list Agent Engines. Please try again shortly."}

    def get_agent_engine_detail(resource_name: str) -> dict:
        """Get detailed metadata for a specific Vertex AI Agent Engine.

        Args:
            resource_name: Full resource name, e.g.
                           "projects/my-project/locations/us-central1/reasoningEngines/12345"

        Returns:
            dict with engine metadata including state, timestamps, and description.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        if not resource_name:
            return {"status": "error", "message": "resource_name is required."}

        try:
            _init_vertexai()
            from vertexai import agent_engines

            engine = agent_engines.get(resource_name)
            return {
                "status": "success",
                "resource_name": engine.resource_name,
                "display_name": getattr(engine, "display_name", ""),
                "state": str(getattr(engine, "state", "UNKNOWN")),
                "create_time": str(getattr(engine, "create_time", "")),
                "update_time": str(getattr(engine, "update_time", "")),
                "description": getattr(engine, "description", ""),
            }
        except Exception as exc:
            err = str(exc)
            logger.error("get_agent_engine_detail error: %s", err)
            if "404" in err or "NOT_FOUND" in err:
                return {"status": "error", "message": f"Agent Engine not found: {resource_name}"}
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied. Ensure roles/aiplatform.viewer is granted."}
            return {"status": "error", "message": "Unable to retrieve Agent Engine details. Please try again shortly."}

    def list_model_endpoints(page_size: int = 50) -> dict:
        """List all Vertex AI online prediction endpoints in the configured region.

        Includes Model Garden endpoints, custom model endpoints, and any
        endpoint used for online inference.

        Args:
            page_size: Maximum endpoints to return (1–100). Default 50.

        Returns:
            dict with list of endpoints including display name, state, and model count.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        if not project:
            return {"status": "error", "message": "GCP project is not configured."}

        try:
            from google.cloud import aiplatform

            aiplatform.init(project=project, location=location)
            page_size = max(1, min(page_size, 100))

            endpoints_data = []
            for ep in aiplatform.Endpoint.list():
                deployed_models = getattr(ep, "deployed_models", []) or []
                endpoints_data.append({
                    "resource_name": ep.resource_name,
                    "display_name": getattr(ep, "display_name", ""),
                    "create_time": str(getattr(ep, "create_time", "")),
                    "update_time": str(getattr(ep, "update_time", "")),
                    "deployed_model_count": len(deployed_models),
                    "traffic_split": getattr(ep, "traffic_split", {}),
                })
                if len(endpoints_data) >= page_size:
                    break

            logger.info("list_model_endpoints: count=%d", len(endpoints_data))
            return {
                "status": "success",
                "location": location,
                "count": len(endpoints_data),
                "endpoints": endpoints_data,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("list_model_endpoints error: %s", err)
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied listing endpoints. Ensure roles/aiplatform.viewer is granted."}
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                return {"status": "error", "message": "Vertex AI API rate limited. Please wait 30 seconds and retry."}
            return {"status": "error", "message": "Unable to list model endpoints. Please try again shortly."}

    def list_deployed_models(endpoint_resource_name: str) -> dict:
        """List all models deployed to a specific Vertex AI endpoint.

        Returns model details including model ID, machine type, accelerator,
        and traffic split percentage.

        Args:
            endpoint_resource_name: Full endpoint resource name.

        Returns:
            dict with list of deployed models and their configurations.
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        if not endpoint_resource_name:
            return {"status": "error", "message": "endpoint_resource_name is required."}

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

        try:
            from google.cloud import aiplatform

            aiplatform.init(project=project, location=location)
            ep = aiplatform.Endpoint(endpoint_name=endpoint_resource_name)
            deployed = getattr(ep, "deployed_models", []) or []
            traffic = getattr(ep, "traffic_split", {}) or {}

            models = []
            for dm in deployed:
                dm_id = getattr(dm, "id", "")
                models.append({
                    "deployed_model_id": dm_id,
                    "model": getattr(dm, "model", ""),
                    "display_name": getattr(dm, "display_name", ""),
                    "machine_type": getattr(getattr(dm, "dedicated_resources", None), "machine_spec", {}).get("machine_type", "") if hasattr(dm, "dedicated_resources") and dm.dedicated_resources else "shared",
                    "traffic_pct": traffic.get(dm_id, 0),
                    "create_time": str(getattr(dm, "create_time", "")),
                })

            logger.info("list_deployed_models: endpoint=%s models=%d", endpoint_resource_name, len(models))
            return {
                "status": "success",
                "endpoint_resource_name": endpoint_resource_name,
                "deployed_model_count": len(models),
                "models": models,
            }
        except Exception as exc:
            err = str(exc)
            logger.error("list_deployed_models error: %s", err)
            if "404" in err or "NOT_FOUND" in err:
                return {"status": "error", "message": f"Endpoint not found: {endpoint_resource_name}"}
            if "403" in err or "PERMISSION_DENIED" in err:
                return {"status": "error", "message": "Permission denied. Ensure roles/aiplatform.viewer is granted."}
            return {"status": "error", "message": "Unable to list deployed models. Please try again shortly."}

    def get_vertex_resource_summary() -> dict:
        """Return a combined summary of all Vertex AI resources.

        Combines Agent Engine count, endpoint count, and highlights any
        resources in non-ACTIVE states. Use this for a quick inventory overview.

        Returns:
            dict with engine_count, endpoint_count, and any anomalies (FAILED/CREATING states).
        """
        disabled = _check_enabled()
        if disabled:
            return disabled

        engine_result = list_agent_engines(page_size=100)
        endpoint_result = list_model_endpoints(page_size=100)

        anomalies = []
        if engine_result.get("status") == "success":
            for e in engine_result.get("engines", []):
                state = e.get("state", "")
                if "FAILED" in state or "ERROR" in state:
                    anomalies.append(f"Agent Engine '{e.get('display_name', e.get('resource_name', ''))}' is in state {state}.")

        return {
            "status": "success",
            "agent_engines": {
                "count": engine_result.get("count", 0) if engine_result.get("status") == "success" else None,
                "status": engine_result.get("status"),
            },
            "model_endpoints": {
                "count": endpoint_result.get("count", 0) if endpoint_result.get("status") == "success" else None,
                "status": endpoint_result.get("status"),
            },
            "anomalies": anomalies,
        }

    return [
        list_agent_engines,
        get_agent_engine_detail,
        list_model_endpoints,
        list_deployed_models,
        get_vertex_resource_summary,
    ]
