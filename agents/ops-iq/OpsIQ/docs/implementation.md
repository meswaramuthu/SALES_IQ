# OpsIQ — Implementation Guide

## 1. Prerequisites

Before starting, ensure the following are available:

### GCP
- [ ] GCP project with billing enabled (`ninth-archway-496404-s2`)
- [ ] `gcloud` CLI installed and authenticated (`gcloud auth login`)
- [ ] Application Default Credentials set (`gcloud auth application-default login`)
- [ ] APIs enabled: Vertex AI, Cloud Monitoring, Cloud Quotas, Firestore, Cloud Storage, Cloud Run, Cloud Scheduler

### Local Tooling
- [ ] Python 3.11–3.12
- [ ] `uv` package manager (`pip install uv`)
- [ ] Docker (for scheduler image builds)
- [ ] `gcloud` CLI ≥ 470

### GCP IAM Roles (service account)
| Role | Purpose |
|---|---|
| `roles/monitoring.viewer` | Cloud Monitoring time-series reads |
| `roles/serviceusage.serviceUsageViewer` | Cloud Quotas list/get |
| `roles/aiplatform.viewer` | Vertex AI Agent Engine + Endpoint listing |
| `roles/datastore.viewer` | Firestore usage queries |
| `roles/storage.objectViewer` | GCS config/prompt reads |
| `roles/datastore.user` | Firestore usage event writes (callbacks) |

---

## 2. Repository Layout

All code lives under `laabu-ai-app/`:

```
laabu-ai-app/
├── agents/ops-iq/OpsIQ/    ← agent source
│   ├── agent.py             ← ADK Agent definition
│   ├── config.py            ← GCS-backed TTL config loader
│   ├── prompts.py           ← dynamic instruction builder
│   ├── callbacks.py         ← tool name fix + usage tracking
│   ├── config/              ← tools_config.json + prompt.txt
│   ├── deploy/              ← deployment scripts
│   ├── scheduler/           ← Cloud Run Job (scheduled checks)
│   └── docs/                ← this document
├── tools/                   ← all tool modules (by GCP service)
└── deployment/              ← central deploy entrypoints
```

Python path when running:
- `PYTHONPATH=<OpsIQ dir>:<laabu-ai-app dir>`

---

## 3. Local Development Setup

### Step 1 — Install dependencies

```bash
cd agents/ops-iq/OpsIQ
uv sync
```

This reads `pyproject.toml` and installs all dependencies into `.venv`.

### Step 2 — Configure environment

```bash
cp env.example .env
# Edit .env — fill in GOOGLE_CLOUD_PROJECT, STAGING_BUCKET, etc.

cp config/tools_config.example.json config/tools_config.json
# Edit tools_config.json to enable/disable monitoring modules
```

Key `.env` variables:
| Variable | Example | Purpose |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | `ninth-archway-496404-s2` | GCP project |
| `STAGING_BUCKET` | `gs://ninth-archway-496404-s2-staging` | Vertex AI staging |
| `TOOLS_CONFIG_GCS_URI` | `gs://stratova-platform/agents/ops-iq/config/tools_config.json` | Runtime config |
| `PROMPT_GCS_URI` | `gs://stratova-platform/agents/ops-iq/prompts/prompt.txt` | Runtime prompt |
| `EMAIL_MCP_URL` | `https://stratova-email-mcp-xxx.run.app/mcp` | Alert email dispatch |
| `FIRESTORE_USAGE_COLLECTION` | `ops_iq_usage` | Usage tracking collection |

### Step 3 — Run locally (ADK web UI)

ADK discovers the agent by looking for the `OpsIQ` subdirectory, so run from the **parent** of `OpsIQ/`:

```bash
cd agents/ops-iq                      # parent of OpsIQ/
AGENT=$(pwd)/OpsIQ
ROOT=$(pwd)/../..                     # laabu-ai-app/ repo root

PYTHONPATH="$AGENT:$ROOT" OpsIQ/.venv/bin/adk web --port 8086
```

Then open `http://127.0.0.1:8086` and select **OpsIQ** from the app list.

Or with the CLI runner (from the same parent directory):
```bash
PYTHONPATH="$AGENT:$ROOT" OpsIQ/.venv/bin/adk run OpsIQ
```

### Step 4 — Run tests

```bash
cd agents/ops-iq/OpsIQ
uv run pytest evaluation/ -v
```

---

## 4. Configuration

### tools_config.json

All monitoring modules are controlled by `config/tools_config.json`. Changes take effect within 60 seconds (config TTL) — no redeploy needed.

```jsonc
{
  "prompt": {
    "source": "gcs",
    "gcs_uri": "gs://stratova-platform/agents/ops-iq/prompts/prompt.txt"
  },
  "tools": {
    "quota_monitoring":  { "enabled": true,  "config": { "services": ["aiplatform.googleapis.com"] } },
    "metrics_monitoring": { "enabled": true,  "config": { "default_lookback_hours": 24, "max_lookback_hours": 168 } },
    "vertex_resources":  { "enabled": true,  "config": { "location": "env:GOOGLE_CLOUD_LOCATION" } },
    "user_usage_tracking": { "enabled": true, "config": { "firestore_collection": "ops_iq_usage" } },
    "gemini_enterprise": { "enabled": false, "config": {} },
    "alerting": {
      "enabled": true,
      "config": {
        "email_mcp_url": "env:EMAIL_MCP_URL",
        "to_emails": ["admin@stratova.ai"],
        "thresholds": { "error_rate_pct": 2.0, "latency_p99_ms": 30000, "token_daily_budget": 5000000 }
      }
    }
  }
}
```

Secrets use the `env:VAR_NAME` pattern — the value is resolved from the Agent Engine environment at runtime, never stored in GCS.

### Upload config/prompt to GCS

```bash
# Upload config
PYTHONPATH="$(pwd):$(pwd)/../../.." python deploy/scripts/upload_config.py

# Upload prompt
PYTHONPATH="$(pwd):$(pwd)/../../.." python deploy/scripts/upload_prompt.py
```

---

## 5. Deployment

### Option A — Full Deploy (recommended first time)

```bash
cd agents/ops-iq/OpsIQ
uv run python deploy/deploy_full.py \
  --project ninth-archway-496404-s2 \
  --staging-bucket gs://ninth-archway-496404-s2-staging
```

This runs three phases:
1. **Infrastructure** — enables required GCP APIs, validates staging bucket
2. **Config Upload** — uploads `tools_config.json` and `prompt.txt` to GCS
3. **Agent Engine Deploy** — packages and deploys `AdkApp` to Vertex AI Agent Engine

The resource name is saved to `deploy/deployment_state.json` and `.env` (`AGENT_ENGINE_ID`).

### Option B — Agent-Only Deploy (skip infra check)

```bash
uv run python deploy/deploy_full.py --skip-infrastructure \
  --project ninth-archway-496404-s2 \
  --staging-bucket gs://ninth-archway-496404-s2-staging
```

### Option C — Direct Deploy (minimal)

```bash
cd agents/ops-iq/OpsIQ
GOOGLE_CLOUD_PROJECT=ninth-archway-496404-s2 \
STAGING_BUCKET=gs://ninth-archway-496404-s2-staging \
uv run python deploy/deploy.py
```

### Teardown

```bash
uv run python deploy/deploy_full.py --delete --project ninth-archway-496404-s2
```

---

## 6. Scheduler Setup

The scheduler runs as a Cloud Run Job on a cron schedule. Build context is the repo root.

### Build and push image

```bash
cd laabu-ai-app/
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/ninth-archway-496404-s2/stratova/ops-iq-scheduler:latest \
  --file agents/ops-iq/OpsIQ/scheduler/Dockerfile \
  .
```

### Create Cloud Run Job

```bash
gcloud run jobs create ops-iq-alert-check \
  --image us-central1-docker.pkg.dev/ninth-archway-496404-s2/stratova/ops-iq-scheduler:latest \
  --region us-central1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=ninth-archway-496404-s2 \
  --set-env-vars FIRESTORE_USAGE_COLLECTION=ops_iq_usage \
  --set-env-vars EMAIL_MCP_URL=$EMAIL_MCP_URL
```

Or use the provided script:
```bash
bash deploy/sync_deploy.sh
```

### Test locally

```bash
cd agents/ops-iq/OpsIQ
PYTHONPATH="$(pwd):$(pwd)/../../.." python scheduler/run_scheduled_check.py --check-only
PYTHONPATH="$(pwd):$(pwd)/../../.." python scheduler/run_scheduled_check.py --report
PYTHONPATH="$(pwd):$(pwd)/../../.." python scheduler/run_scheduled_check.py --eod-summary
```

---

## 7. Post-Deploy Smoke Test

```bash
cd agents/ops-iq/OpsIQ
# AGENT_ENGINE_ID must be set in .env
uv run python deploy/run.py
```

This runs 5 test queries against the deployed agent and streams the responses.

---

## 8. Makefile Quick Reference

| Command | Action |
|---|---|
| `make install` | Install dependencies (`uv sync`) |
| `make web` | Run ADK web UI locally |
| `make run` | Run ADK CLI locally |
| `make test` | Run evaluation test suite |
| `make lint` | Lint with ruff |
| `make format` | Auto-format with ruff |
| `make check` | Run scheduled threshold check locally |
| `make eod-summary` | Run EOD summary check locally |
| `make deploy-full` | Full 3-phase deploy |
| `make deploy-agent-only` | Deploy agent only (skip infra) |
| `make upload-config` | Upload tools_config.json to GCS |
| `make upload-prompt` | Upload prompt.txt to GCS |
| `make delete-all` | Teardown Agent Engine |
