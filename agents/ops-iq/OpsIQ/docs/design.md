# OpsIQ — System Design Document

## 1. Overview

OpsIQ is a GCP resource monitoring and observability agent built on Google's Agent Development Kit (ADK) and deployed to Vertex AI Agent Engine. It provides a conversational interface for querying Vertex AI quotas, Cloud Monitoring time-series metrics (tokens, requests, latency, error rates), Vertex AI resource inventory (Agent Engines, endpoints, models), per-user usage tracking via Firestore, and threshold-based alerting via email.

All monitoring modules are togglable at runtime through a GCS-backed config file without redeployment.

---

## 2. Architecture

### Architecture Overview (ASCII)

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Gemini AI Enterprise / ADK web UI                  │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ REST / gRPC
┌────────────────────────────▼─────────────────────────────────────────┐
│                   Vertex AI Agent Engine                              │
│                 (Cloud-managed ADK runtime)                           │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  Agent  (Gemini 2.5 Flash)                                   │    │
│  │  ├─ Dynamic prompt  ←── GCS: prompt.txt                      │    │
│  │  ├─ Dynamic config  ←── GCS: tools_config.json (TTL 60s)    │    │
│  │  └─ ~22 registered tools (5 categories)                      │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  Tool categories:                                                     │
│  ├─ Quota (3 tools)      ── Cloud Quotas API                         │
│  ├─ Metrics (7 tools)    ── Cloud Monitoring time-series             │
│  ├─ Vertex (5 tools)     ── Vertex AI Admin API                      │
│  ├─ Firestore (6 tools)  ── Per-user usage DB                        │
│  └─ Alerting (3 tools)   ── Email MCP server                         │
└──────────────────────────────────────────────────────────────────────┘
                             │
           ┌─────────────────┼───────────────────┐
           ▼                 ▼                   ▼
    ┌─────────────┐  ┌──────────────┐  ┌────────────────┐
    │  Firestore  │  │  Cloud Run   │  │  GCS Bucket    │
    │ (usage DB)  │  │  Scheduler   │  │ (config,       │
    └─────────────┘  └──────────────┘  │  prompts)      │
                             │         └────────────────┘
              ┌──────────────┘
              ▼
    Cloud Monitoring / Cloud Quotas API / Vertex AI Admin API
```

---

## 3. Component Breakdown

### 3.1 Agent Core (`OpsIQ/`)

| File | Role |
|---|---|
| `agent.py` | ADK `Agent` definition — registers 22 tools, binds dynamic instruction + after_model_callback |
| `config.py` | TTL-cached config loader — reads `tools_config.json` from GCS every 60s |
| `prompts.py` | Callable instruction — injects tool status + UTC datetime on every invocation |
| `callbacks.py` | Strips qualified tool names (ADK bug workaround) + writes usage events to Firestore |
| `agent_engine_app.py` | Vertex AI deployment wrapper (`AdkApp`) |

### 3.2 Tools (`laabu-ai-app/tools/`)

All tools are **always registered** at startup. Each tool re-reads config on every call, so enabling/disabling a monitoring module in `tools_config.json` takes effect within 60 seconds without restart.

| Category | File | Tools |
|---|---|---|
| Quota | `google/quota_tool.py` | `list_vertex_quotas`, `get_quota_preferences`, `get_vertex_quota_summary` |
| Metrics | `google/metrics_tool.py` | `get_token_usage`, `get_request_counts`, `get_latency_stats`, `get_error_rates`, `get_quota_usage_metrics`, `get_agent_engine_metrics`, `get_platform_metrics_summary` |
| Vertex Resources | `vertex/vertex_resources_tool.py` | `list_agent_engines`, `get_agent_engine_detail`, `list_model_endpoints`, `list_deployed_models`, `get_vertex_resource_summary` |
| Firestore Usage | `firestore/usage_tracker_tool.py` | `get_user_usage_summary`, `get_top_users`, `get_session_history`, `get_agent_usage_breakdown`, `aggregate_daily_user_usage`, `aggregate_daily_agent_usage` |
| Alerting | `alerting/alerting_tool.py` | `check_thresholds`, `send_alert_email`, `send_status_report`, `send_user_usage_report`, `send_agent_usage_report`, `send_eod_summary` |

### 3.3 Scheduler (`OpsIQ/scheduler/`)

A Cloud Run Job that runs outside the ADK agent runtime, directly calling tools to generate reports and send alerts on a cron schedule.

| Component | Description |
|---|---|
| `run_scheduled_check.py` | CLI entry point — `--report`, `--check-only`, `--user-report`, `--agent-report`, `--eod-summary` |
| `Dockerfile` | Build context is repo root (`laabu-ai-app/`); sets `PYTHONPATH=/app:/app/OpsIQ` |

---

## 4. Key Design Decisions

### 4.1 Dynamic Config (No Restart Required)
`config.py` fetches `tools_config.json` from GCS and caches it for 60 seconds (configurable via `CONFIG_CACHE_TTL_SECONDS`). This means operators can enable/disable any monitoring module or update thresholds at runtime — no redeployment needed.

Secrets in config are resolved via `env:VAR_NAME` — the value is read from the Agent Engine's environment variable at runtime, never stored in GCS.

### 4.2 All Tools Always Registered
The ADK agent registers all ~22 tools at startup rather than dynamically adding/removing them. Each tool checks its enabled flag on every call and returns a `{"status": "disabled"}` response if off. This avoids gRPC serialization issues that can occur with dynamic tool lists (ADK limitation in v1.34.3).

### 4.3 after_model_callback Chain
`callbacks.py` chains two operations in `_after_model`:
1. `strip_agent_name_prefix` — strips `ops_iq_agent.toolname` → `toolname` to fix ADK 1.34.3 ValueError on qualified names from Gemini 2.5.
2. `capture_usage` — writes token counts to Firestore in the background (non-blocking, silently ignored on failure).

### 4.4 Threshold-Based Alerting
Alerting thresholds (error rate %, latency p99 ms, daily token budget, quota utilisation %) live in `tools_config.json` and can be tuned at runtime without redeploying. The `check_thresholds` tool runs all metric checks and returns a `violation_count` — the scheduler uses exit code 1 when violations are found, making it CI/pager-integration friendly.

### 4.5 Registry Pattern
`tools/ops_iq_registry.py` is the single entry point that aggregates `get_all_tools()` from all 5 tool modules. `agent.py` imports only from the registry, keeping the agent core clean.

---

## 5. Data Flow

### Query Flow (User → Agent → Tool → Response)
```
User message
    → Agent receives (via Gemini AI Enterprise or ADK web UI)
    → build_instruction() called → fetches prompt.txt from GCS + injects tool status + UTC time
    → Gemini 2.5 Flash reasons over message + tools list
    → Tool called (e.g. get_token_usage)
        → get_config() called → reads tools_config.json from GCS (or 60s cache)
        → Cloud Monitoring API queried
        → Results returned to model
    → Model generates final response
    → after_model_callback: strip_agent_name_prefix + capture_usage (Firestore write)
    → Response returned to user
```

### Scheduler Flow (Cron → Alert / Report)
```
Cloud Scheduler (e.g. every 2h / daily 08:00)
    → Cloud Run Job (scheduler/run_scheduled_check.py)
        → Loads .env, sets PYTHONPATH
        → Calls alerting_tool.get_tools() → runs check_thresholds / send_alert_email / send_eod_summary
            → Queries Cloud Monitoring for current metrics
            → Compares against configured thresholds
            → If violations: POST to Email MCP server → sends alert email
        → Exit code 0 (healthy) / 1 (violations) / 2 (error)
```

---

## 6. Security Considerations

| Concern | Mitigation |
|---|---|
| Secrets in config | All secrets use `env:VAR_NAME` — stored in Agent Engine env, never in GCS |
| Cross-user data | Firestore queries are scoped to `user_id`; agent requires explicit user_id confirmation before fetching another user's data |
| Read-only APIs | All GCP APIs used are read-only (monitoring.viewer, serviceusage.serviceUsageViewer, aiplatform.viewer, datastore.viewer) |
| Service account | Runs under a dedicated SA with least-privilege IAM; no write access to monitored resources |
| Email dispatch | Uses dedicated Email MCP server (Cloud Run); authenticated via OIDC ID token per request |

---

## 7. Folder Structure

```
laabu-ai-app/
├── agents/ops-iq/OpsIQ/
│   ├── agent.py, config.py, prompts.py, callbacks.py   ← agent core
│   ├── config/                                          ← GCS-backed runtime config
│   │   ├── tools_config.json
│   │   ├── tools_config.example.json
│   │   └── prompt.txt
│   ├── deploy/                                          ← deployment scripts
│   │   ├── deploy_full.py          (3-phase orchestrated deploy)
│   │   ├── deploy.py               (direct Agent Engine deploy)
│   │   ├── run.py                  (smoke test vs deployed agent)
│   │   ├── sync_deploy.sh          (Cloud Run Job + Scheduler setup)
│   │   ├── deployment_state.json   (resource IDs, auto-populated)
│   │   └── scripts/                (config/prompt upload utilities)
│   ├── scheduler/                                       ← Cloud Run Job
│   │   ├── run_scheduled_check.py
│   │   └── Dockerfile
│   ├── evaluation/                                      ← ADK eval test cases
│   │   ├── conftest.py
│   │   ├── run_eval.py
│   │   └── test_cases/
│   │       ├── ops_iq.test.json
│   │       └── test_config.json
│   ├── docs/                                            ← this document and others
│   ├── agent-card/                                      ← A2A agent metadata
│   └── memory/                                          ← project notes
├── tools/
│   ├── google/quota_tool.py          ← Cloud Quotas API (3 tools)
│   ├── google/metrics_tool.py        ← Cloud Monitoring (7 tools)
│   ├── vertex/vertex_resources_tool.py ← Vertex AI Admin (5 tools)
│   ├── firestore/usage_tracker_tool.py ← Firestore per-user usage (6 tools)
│   ├── alerting/alerting_tool.py     ← Threshold alerting + email (6 tools)
│   ├── ops_iq_registry.py            ← OpsIQ tool aggregator
│   └── utils/gcs_utils.py            ← shared GCS read/write utilities
```
