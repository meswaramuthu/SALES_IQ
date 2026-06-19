# enterpriseGPT — Implementation Guide

## 1. Prerequisites

Before starting, ensure the following are available:

### GCP
- [ ] GCP project with billing enabled (`ninth-archway-496404-s2`)
- [ ] `gcloud` CLI installed and authenticated (`gcloud auth login`)
- [ ] Application Default Credentials set (`gcloud auth application-default login`)
- [ ] APIs enabled: Vertex AI, Cloud Run, Cloud Storage, Artifact Registry, Secret Manager, Cloud Scheduler

### Local Tooling
- [ ] Python 3.11–3.12
- [ ] `uv` package manager (`pip install uv`)
- [ ] Docker (for sync service image builds)
- [ ] `gcloud` CLI ≥ 470

### Third-Party Credentials
| Service | Credential Needed |
|---|---|
| GitHub | Personal Access Token (`repo`, `read:org`) |
| Jira / Confluence | API token from `id.atlassian.com` |
| SharePoint | Azure AD App Registration (Application permissions: `Sites.Read.All`, `Files.Read.All`) |
| Gmail / Drive | Service account JSON with domain-wide delegation |

---

## 2. Repository Layout

All code lives under `new_folder_structure/`:

```
new_folder_structure/
├── agents/knowledge-iq/enterpriseGPT/   ← agent source
│   ├── agent.py                          ← ADK Agent definition
│   ├── config.py                         ← GCS-backed TTL config loader
│   ├── prompts.py                        ← dynamic instruction builder
│   ├── config/                           ← tools_config.json + prompt.txt
│   ├── deploy/                           ← deployment scripts
│   ├── scheduler/                        ← sync service (Cloud Run)
│   └── docs/                             ← this document
├── tools/                                ← all 37 tool modules (by vendor)
└── deployment/                           ← central deploy entrypoints
```

Python path when running:
- `PYTHONPATH=<enterpriseGPT dir>:<new_folder_structure dir>`

---

## 3. Local Development Setup

### Step 1 — Install dependencies

```bash
cd agents/knowledge-iq/enterpriseGPT
uv sync
```

This reads `pyproject.toml` and installs all dependencies into `.venv` inside the `knowledge-iq/` directory.

To install the editable `stratova_shared` package:
```bash
uv pip install -e ../shared
```

### Step 2 — Configure environment

```bash
cp config/tools_config.example.json config/tools_config.json
# Edit tools_config.json — fill in your credentials
# Use "env:VAR_NAME" for secrets (they'll be read from env vars at runtime)

cp .env .env.local
# Edit .env.local with your GCP project, bucket, corpus IDs
```

Key `.env` variables:

| Variable | Description |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Region (e.g. `us-central1`) |
| `TOOLS_CONFIG_GCS_URI` | GCS URI for `tools_config.json` |
| `PROMPT_GCS_URI` | GCS URI for `prompt.txt` |
| `RAG_CORPUS` | Full Vertex AI RAG corpus resource name |
| `STAGING_BUCKET` | GCS bucket for ADK staging |

### Step 3 — Upload config to GCS

```bash
cd deploy/scripts
python upload_config.py     # uploads tools_config.json to GCS
python upload_prompt.py     # uploads config/prompt.txt to GCS
```

### Step 4 — Run locally

```bash
VENV=../../.venv   # adjust to venv location
ROOT=$(pwd)/../../..   # new_folder_structure root
AGENT=$(pwd)

cd ..   # run from parent of enterpriseGPT/

PYTHONPATH="$AGENT:$ROOT" $VENV/bin/adk web . --port 8082
```

Open `http://127.0.0.1:8082` in your browser. Select **enterpriseGPT** from the app list.

---

## 4. First-Time GCP Setup

Run this once to bootstrap all GCP infrastructure:

```bash
cd deploy
python deploy_full.py
```

This script handles all 5 phases automatically:

| Phase | What It Does |
|---|---|
| 1. Infrastructure | Creates GCS bucket, Artifact Registry repo, Service Account + IAM bindings |
| 2. RAG Corpus | Creates Vertex AI RAG corpus with `text-embedding-004` |
| 3. Config Upload | Uploads `tools_config.json` and `prompt.txt` to GCS |
| 4. Agent Engine | Builds wheel, deploys ADK app to Vertex AI Agent Engine |
| 5. Gemini Enterprise | Registers agent with Gemini AI Enterprise connector |

Deployed resource IDs are saved to `deploy/deployment_state.json`.

### Alternative: Central deploy script

```bash
# From new_folder_structure/ root:
export GCP_PROJECT=ninth-archway-496404-s2
export GCS_BUCKET=ninth-archway-496404-s2-knowledge-iq
./deployment/deploy_agent.sh
```

---

## 5. Connector Setup

### RAG Corpus (required)

```bash
# Create a new corpus and seed with sample documents
python deploy/scripts/setup_corpus.py \
  --display-name "enterpriseGPT-corpus" \
  --seed-gcs-folder gs://your-bucket/seed-docs/
```

### Validate each connector before enabling

```bash
python deploy/scripts/setup_connector.py --connector github
python deploy/scripts/setup_connector.py --connector sharepoint
python deploy/scripts/setup_connector.py --connector jira
python deploy/scripts/setup_connector.py --connector confluence
python deploy/scripts/setup_connector.py --connector gmail
```

Each command tests the credentials against the live API and reports success or detailed error before you commit the config.

---

## 6. Sync Service Deployment

The sync service is a separate Cloud Run deployment. It keeps the RAG corpus up-to-date by syncing SharePoint and GitHub content on a schedule and via webhooks.

```bash
# From new_folder_structure/ root:
export GCP_PROJECT=ninth-archway-496404-s2
export GCS_BUCKET=ninth-archway-496404-s2-knowledge-iq
./deployment/deploy_cloudrun.sh --scheduler
```

Or run the dedicated script:

```bash
bash deploy/sync_deploy.sh
```

This deploys:
1. **Cloud Run Job** — triggered by Cloud Scheduler (`0 * * * *` — hourly)
2. **Cloud Run Service** — always-on webhook receiver for SharePoint Graph notifications and GitHub push events

---

## 7. Runtime Configuration (No Restart)

All settings in `tools_config.json` take effect within **60 seconds** without redeployment.

### Enable / disable a tool

```bash
# Edit tools_config.json locally — set "enabled": true/false
# Then upload:
python deploy/scripts/upload_config.py
```

### Update the system prompt

```bash
# Edit config/prompt.txt
python deploy/scripts/upload_prompt.py
```

### Update agent code

```bash
python deploy/update_agent.py
# Fast path: uploads config to GCS then updates Agent Engine with new code wheel
```

---

## 8. Environment Variables Reference

Set these in Vertex AI Agent Engine (Settings → Environment Variables) for production:

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | ✅ | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | ✅ | Region (us-central1) |
| `TOOLS_CONFIG_GCS_URI` | ✅ | GCS URI for tools config |
| `PROMPT_GCS_URI` | ✅ | GCS URI for system prompt |
| `RAG_CORPUS` | ✅ | Vertex AI RAG corpus resource name |
| `RAG_LOCATION` | ✅ | RAG corpus region |
| `STAGING_BUCKET` | ✅ | GCS bucket for ADK wheel staging |
| `GITHUB_TOKEN` | Optional | GitHub PAT (if enabled) |
| `JIRA_API_TOKEN` | Optional | Atlassian API token |
| `CONFLUENCE_API_TOKEN` | Optional | Atlassian API token |
| `SHAREPOINT_CLIENT_SECRET` | Optional | Azure AD app secret |

---

## 9. Smoke Test After Deployment

```bash
python deploy/run.py
```

This creates a session with the deployed Agent Engine and sends 3 test queries:
1. `"What tools do you have available?"` — tests agent reasoning + prompt loading
2. `"List my documents."` — tests RAG tool + corpus connection
3. `"List GitHub repos."` — tests GitHub connector (if enabled)

Expected: all 3 return valid responses within 30 seconds.

---

## 10. Monitoring & Operations

| Concern | Where to Look |
|---|---|
| Agent logs | GCP Console → Vertex AI → Agent Engine → Logs |
| Sync job logs | GCP Console → Cloud Run → Jobs → knowledge-iq-sync |
| Webhook service logs | GCP Console → Cloud Run → Services → knowledge-iq-webhook |
| RAG corpus stats | GCP Console → Vertex AI → RAG Engine |
| Config changes | GCS bucket → `knowledge-iq/tools_config.json` |

### Common Issues

| Symptom | Likely Cause | Fix |
|---|---|---|
| Tool returns "disabled" | Tool not enabled in `tools_config.json` | Upload updated config |
| GCS config load fails | ADC expired | Run `gcloud auth application-default login` |
| SharePoint 401 error | Azure AD client secret expired | Rotate secret, update env var |
| GitHub rate-limit errors | PAT exhausted | Use a higher-quota PAT or enable OAuth app |
| Sync job exits 0 but no docs ingested | Delta tokens stale | Delete state GCS file to force full re-sync |
| Agent cold start > 30s | No warm instance | Set Cloud Run min-instances = 1 in sync webhook |
