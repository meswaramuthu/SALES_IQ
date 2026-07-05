---
name: opsiq-project-notes
description: Architecture decisions, known issues, and operational notes for OpsIQ
metadata:
  type: project
---

## Agent Purpose

OpsIQ monitors GCP resource usage for the Stratova AI platform. It has 22 tool functions across 5 categories: quota monitoring, Cloud Monitoring metrics, Vertex AI resource inventory, Firestore usage tracking, and threshold-based alerting.

## Import Architecture

OpsIQ uses flat imports at runtime because `OpsIQ/` is on `PYTHONPATH`:
- `from config import get_config` (not `from ops_iq.config`)
- `from prompts import build_instruction`
- `from tools.ops_iq_registry import get_all_tools`

Tools live in `new_folder_structure/tools/` shared directory. At deploy time, the `tools/` directory is temporarily copied into `OpsIQ/` for bundling as `extra_packages`.

## New Folder Structure Migration

This agent was restructured from `agents/ops-iq/` into `new_folder_structure/agents/ops-iq/OpsIQ/` to match the standardised layout established by enterpriseGPT (knowledge-iq). Key changes:

- Agent core files moved from `ops_iq/` sub-package to `OpsIQ/` root
- Tools extracted to shared `new_folder_structure/tools/` namespace under `google/`, `vertex/`, `firestore/`, `alerting/` categories
- `tools/ops_iq_registry.py` created as OpsIQ-specific tool aggregator (separate from `tools/registry.py` which is knowledge-iq specific)
- `deploy/` folder consolidates deployment scripts with a new `deploy_full.py` orchestrator
- `scheduler/` folder contains Cloud Run Job files

## Known Quirks

- **Quota metrics in Cloud Monitoring**: `aiplatform.googleapis.com/quota/*/usage` and `/limit` only emit data when consumption is significant. Absence of data = well below quota limits. Use `list_vertex_quotas` from the Cloud Quotas API for configured limits.
- **Latency threshold exclusions**: Live/streaming/audio/realtime models report session duration as their latency metric, not per-request p99. `alerting_tool.py` excludes these via `_LATENCY_EXCLUDE_PATTERNS`.
- **ADK 1.34.3 qualified tool names**: Gemini 2.5 returns `ops_iq_agent.toolname` in function calls. `strip_agent_name_prefix` in `callbacks.py` strips the prefix before ADK processes it.

## Scheduling

Two Cloud Scheduler jobs trigger the Cloud Run Job:
- `ops-iq-daily-report`: 08:00 UTC daily — always sends `send_status_report`
- `ops-iq-alert-check`: every 2 hours — only emails on threshold violations

## Config / Prompt Hot-Reload

- `TOOLS_CONFIG_GCS_URI` → TTL-cached every 60 seconds
- `PROMPT_GCS_URI` → re-read on every agent invocation (no TTL)
- Enable/disable any tool without redeploying by editing GCS config

## GCS Paths (Production)

- Config: `gs://stratova-platform/agents/ops-iq/config/tools_config.json`
- Prompt: `gs://stratova-platform/agents/ops-iq/prompts/prompt.txt`
- Agent card: `gs://stratova-platform/agents/ops-iq/agent-card/agent-card.json`
