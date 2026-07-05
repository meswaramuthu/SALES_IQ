# OpsIQ — GCP Resource Monitoring & Observability Agent

OpsIQ is the intelligent GCP resource monitoring agent for the Stratova AI platform. It provides a conversational interface to query Vertex AI quotas, Cloud Monitoring time-series metrics, resource inventory, per-user usage tracking, and threshold-based alerting.

---

## Architecture

```
┌───────────────────────────────────────────────────┐
│               Vertex AI Agent Engine               │
│                                                    │
│  Agent (Gemini 2.5 Flash)                          │
│    ├─ Dynamic prompt ←── GCS: prompt.txt           │
│    └─ 22 tools (5 categories)                      │
│         ├─ Quota (3)    → Cloud Quotas API         │
│         ├─ Metrics (7)  → Cloud Monitoring         │
│         ├─ Vertex (5)   → Vertex AI Admin API      │
│         ├─ Firestore (4) → Usage DB                │
│         └─ Alerting (3) → Email MCP server         │
│  Config ←── TTL 60s ←── GCS: tools_config.json    │
└───────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────┐
│         Scheduler (Cloud Run Job)                  │
│  Cloud Scheduler → Cloud Run Job                   │
│    ├─ Daily: send_status_report (08:00 UTC)        │
│    └─ Every 2h: send_alert_email                   │
└───────────────────────────────────────────────────┘
```

## Project Structure

```
OpsIQ/
├── agent.py              ADK Agent definition (Gemini 2.5 Flash, 22 tools)
├── config.py             TTL-cached GCS config loader (60s TTL)
├── prompts.py            Dynamic instruction builder (datetime + tool status)
├── callbacks.py          Usage tracking + tool name prefix stripping
├── agent_engine_app.py   Vertex AI deployment entry point
├── config/               tools_config.json + prompt.txt (GCS-synced)
├── deploy/               Deployment scripts
│   ├── deploy_full.py    Orchestrated deploy (3 phases)
│   ├── deploy.py         Direct Agent Engine deploy
│   ├── sync_deploy.sh    Cloud Run Job + Cloud Scheduler setup
│   ├── deployment_state.json  Resource IDs (auto-populated)
│   └── scripts/          Config/prompt upload utilities
├── docs/                 This file
├── evaluation/           Eval test cases
├── memory/               Project notes
├── scheduler/            Cloud Run Job (scheduled checks)
│   ├── run_scheduled_check.py
│   └── Dockerfile
└── agent-card/           A2A agent card

laabu-ai-app/tools/    (shared tool namespace)
├── google/quota_tool.py       Cloud Quotas API
├── google/metrics_tool.py     Cloud Monitoring
├── vertex/vertex_resources_tool.py  Agent Engines + Endpoints
├── firestore/usage_tracker_tool.py  Per-user usage
├── alerting/alerting_tool.py        Threshold checks + email
└── ops_iq_registry.py               OpsIQ tool aggregator
```

## Quick Start (Local)

```bash
cd laabu-ai-app/agents/ops-iq/OpsIQ
cp .env .env.local     # fill in GOOGLE_CLOUD_PROJECT, STAGING_BUCKET, etc.
uv sync
PYTHONPATH="$(pwd):$(pwd)/../../.." uv run adk run . --port 8083
```

Then open `http://localhost:8083` to chat with the agent.

## Deploy to Vertex AI

```bash
cd laabu-ai-app/agents/ops-iq/OpsIQ
uv run python deploy/deploy_full.py \
  --project ninth-archway-496404-s2 \
  --staging-bucket gs://stratova-staging
```

To teardown:
```bash
uv run python deploy/deploy_full.py --delete --project ninth-archway-496404-s2
```

## Runtime Config Changes (No Redeploy)

```bash
# Edit config/tools_config.json to enable/disable tools, then:
PYTHONPATH="$(pwd):$(pwd)/../../.." python deploy/scripts/upload_config.py

# Edit config/prompt.txt then:
PYTHONPATH="$(pwd):$(pwd)/../../.." python deploy/scripts/upload_prompt.py
```

Changes take effect within 60 seconds (config TTL).

## IAM Requirements

| Role | Purpose |
|---|---|
| `roles/monitoring.viewer` | Cloud Monitoring time-series reads |
| `roles/serviceusage.serviceUsageViewer` | Cloud Quotas list/get |
| `roles/aiplatform.viewer` | Agent Engine + Endpoint listing |
| `roles/datastore.viewer` | Firestore usage queries |
| `roles/storage.objectViewer` | GCS config/prompt reads |

## Environment Variables

| Variable | Purpose |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `STAGING_BUCKET` | GCS staging bucket for Vertex AI packaging |
| `TOOLS_CONFIG_GCS_URI` | GCS URI for runtime tools config JSON |
| `PROMPT_GCS_URI` | GCS URI for runtime system prompt |
| `EMAIL_MCP_URL` | Email MCP server URL for alerting |
| `ALERT_TO_EMAILS` | Comma-separated alert recipient list |
| `FIRESTORE_USAGE_COLLECTION` | Firestore collection for usage tracking |

## Scheduler Setup

```bash
cd laabu-ai-app/agents/ops-iq/OpsIQ
bash deploy/sync_deploy.sh
```

Creates:
- `ops-iq-daily-report` — runs at 08:00 UTC daily, sends full status email
- `ops-iq-alert-check` — runs every 2 hours, emails only on threshold violations
