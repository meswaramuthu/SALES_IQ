# enterpriseGPT (Knowledge IQ) — Enterprise RAG Agent

enterpriseGPT is a multi-source Retrieval-Augmented Generation (RAG) agent built on Google's Agent Development Kit (ADK) and deployed to Vertex AI Agent Engine. It gives users a single conversational interface to query across SharePoint, GitHub, Gmail, Google Drive, Jira, Confluence, and a Vertex AI RAG vector corpus — with all connectors togglable at runtime without redeploying.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Project Structure](#project-structure)
3. [Data Flow](#data-flow)
4. [Tool Connectors](#tool-connectors)
5. [Dynamic Configuration System](#dynamic-configuration-system)
6. [Sync Service](#sync-service)
7. [Prerequisites](#prerequisites)
8. [Local Development Setup](#local-development-setup)
9. [Deploying the Agent](#deploying-the-agent)
10. [Deploying the Sync Service](#deploying-the-sync-service)
11. [Setting Up Gemini AI Enterprise](#setting-up-gemini-ai-enterprise-console-ui)
12. [Runtime Operations (No Restart Required)](#runtime-operations-no-restart-required)
13. [Environment Variables Reference](#environment-variables-reference)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Gemini AI Enterprise                         │
│                    (Agent Builder — deployed app)                   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │  REST / gRPC
┌───────────────────────────────▼─────────────────────────────────────┐
│                    Vertex AI Agent Engine                            │
│                  (Cloud-managed ADK runtime)                         │
│                                                                      │
│   Agent (Gemini 2.5 Flash)                                           │
│     ├─ Dynamic prompt  ←── GCS: prompt.txt                          │
│     └─ 37 tools (7 connector categories — enabled/disabled via cfg)  │
│          │                                                           │
│          ├─ RAG (5)        → Vertex AI RAG Corpus (us-central1)      │
│          ├─ Microsoft (9)  → Microsoft Graph API (SharePoint)        │
│          ├─ GitHub (10)    → GitHub REST API                         │
│          ├─ Google (3)     → Gmail + Google Drive + Gemini Enterprise│
│          ├─ Atlassian (4)  → Jira + Confluence                       │
│          └─ A2A (3)        → CRM Agent + Enrichment + Web Scraper   │
│                                                                      │
│   Config ←── TTL cache (60 s) ←── GCS: tools_config.json            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Scheduler / Sync Service (Cloud Run)             │
│                                                                      │
│   Cloud Scheduler (hourly)                                           │
│     └─ Cloud Run Job (scheduler/job.py)                              │
│          ├─ SharePoint Connector  (Graph deltaLink per drive)         │
│          └─ GitHub Connector      (HEAD SHA compare per repo)        │
│               └─ Vertex AI RAG: upload / delete files                │
│               └─ State → GCS: sync-state.json                        │
│                                                                      │
│   GitHub / SharePoint webhooks                                       │
│     └─ Cloud Run Service (scheduler/webhook_server.py)               │
│          └─ Triggers incremental sync on push events                 │
└─────────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **All tools are always registered** with the ADK Agent. Each tool re-reads the TTL-cached config on every call. Disabled tools return `{"status": "disabled", …}` immediately.
- **Dynamic prompt**: `instruction=build_instruction` is a callable invoked on every agent invocation. It fetches a fresh prompt from GCS and injects the current tool status and UTC timestamp.
- **Config resolution order**: `TOOLS_CONFIG_GCS_URI` → JSON from GCS → individual env var fallback.
- **Secrets pattern**: `"api_token": "env:JIRA_API_TOKEN"` in `tools_config.json`; resolved to actual env var at load time by `_resolve_env_refs()`.

---

## Project Structure

```
new_folder_structure/
├── agents/knowledge-iq/
│   └── enterpriseGPT/                   ← Agent root (add to PYTHONPATH)
│       ├── agent.py                     ← ADK Agent + App construction
│       ├── agent_engine_app.py          ← Re-export for Vertex AI deployment
│       ├── config.py                    ← AgentConfig model + TTL ConfigLoader
│       ├── prompts.py                   ← build_instruction() callable (dynamic prompt)
│       ├── config/
│       │   ├── tools_config.json        ← Runtime connector config (upload to GCS)
│       │   ├── tools_config.example.json
│       │   ├── prompt.txt               ← System prompt (upload to GCS)
│       │   └── prompt.example.txt
│       ├── deploy/
│       │   ├── deploy_full.py           ← Full GCP infra + agent deployment
│       │   ├── deploy.py                ← Agent Engine deploy only
│       │   ├── update_agent.py          ← Update deployed agent
│       │   ├── run.py                   ← Test deployed agent via REST API
│       │   ├── sync_deploy.sh           ← Deploy sync service to Cloud Run
│       │   ├── sync_Dockerfile          ← Docker image for sync job + webhook
│       │   └── scripts/
│       │       ├── setup_corpus.py      ← Create RAG corpus + optional seeding
│       │       ├── setup_connector.py   ← Validate connector credentials
│       │       ├── upload_config.py     ← Push tools_config.json to GCS
│       │       └── upload_prompt.py     ← Push prompt.txt to GCS
│       ├── scheduler/                   ← Background sync service (Cloud Run)
│       │   ├── job.py                   ← Cloud Run Job entry point
│       │   ├── webhook_server.py        ← FastAPI webhook receiver
│       │   ├── config.py                ← Sync env var loader
│       │   ├── state.py                 ← GCS-backed sync state store
│       │   ├── ingestion.py             ← RAG upload/delete helpers
│       │   ├── keyword_extractor.py     ← Gemini Flash metadata extraction
│       │   └── connectors/
│       │       ├── base.py              ← BaseConnector ABC + SyncResult
│       │       ├── sharepoint.py        ← SharePoint Graph delta connector
│       │       └── github.py            ← GitHub SHA compare connector
│       ├── agent-card/
│       │   └── agent-card.json          ← Gemini Enterprise agent metadata
│       ├── docs/                        ← Documentation (this file)
│       ├── evaluation/demo-documents/   ← Sample docs for RAG seeding
│       ├── memory/                      ← Project notes
│       ├── pyproject.toml
│       ├── .env                         ← Local environment variables
│       └── Makefile
│
├── tools/                               ← Tool modules (add to PYTHONPATH)
│   ├── registry.py                      ← get_all_tools() — aggregates all tools
│   ├── utils/
│   │   └── gcs_utils.py                 ← GCS read/write helpers
│   ├── rag/
│   │   ├── rag_tool.py                  ← Vertex AI RAG — 4 corpus tools
│   │   └── user_rag_tool.py             ← Per-user RAG upload/list/delete
│   ├── google/
│   │   ├── gmail_tool.py                ← Gmail API — 2 tools
│   │   ├── gdrive_tool.py               ← Google Drive API — 2 tools
│   │   └── gemini_connector_tool.py     ← Gemini Enterprise search — 1 tool
│   ├── atlassian/
│   │   ├── jira_tool.py                 ← Atlassian Jira — 2 tools
│   │   └── confluence_tool.py           ← Atlassian Confluence — 2 tools
│   ├── microsoft/
│   │   └── sharepoint_tool.py           ← Microsoft Graph API — 12 tools
│   ├── github/
│   │   └── github_tool.py               ← GitHub REST API — 10 tools
│   └── a2a/
│       └── a2a_tools.py                 ← Agent-to-Agent routing — 3 tools
│
└── deployment/
    ├── deploy_agent.sh                  ← Central entry point: full agent deploy
    └── deploy_cloudrun.sh               ← Cloud Run services + scheduler
```

**PYTHONPATH must include both**:
- `new_folder_structure/agents/knowledge-iq/enterpriseGPT/` — for `config`, `prompts`, `agent`, `scheduler`
- `new_folder_structure/` — for `tools`

---

## Data Flow

### Agent Request Flow

```
User message (via Gemini AI Enterprise or API)
  │
  ▼
Vertex AI Agent Engine
  │
  ├─ 1. build_instruction(context) called
  │       └─ get_config() → TTL cache → GCS tools_config.json (if expired)
  │       └─ fetch prompt.txt from GCS (or use default)
  │       └─ inject {tool_status} + {current_datetime}
  │
  ├─ 2. Gemini 2.5 Flash processes message + prompt
  │       └─ decides which tool(s) to call
  │
  ├─ 3. Tool function called (e.g., search_knowledge_base)
  │       └─ get_config() → check enabled status
  │       └─ if disabled → return {"status": "disabled", ...}
  │       └─ if enabled → make API call → return result
  │
  └─ 4. Agent synthesizes response from tool outputs
          └─ streamed back to user
```

### Sync Job Flow

```
Cloud Scheduler (hourly cron)
  │
  ▼
Cloud Run Job: python -m scheduler.job
  │
  ├─ Load agent config from TOOLS_CONFIG_GCS_URI
  ├─ Load sync state from SYNC_STATE_GCS_URI (GCS JSON blob)
  │     └─ If not found: start fresh (triggers full crawl)
  │
  ├─ SharePoint Connector
  │     ├─ For each drive: GET /drives/{id}/root/delta?token={deltaLink}
  │     ├─ For new/modified files: download → upload_to_rag() → store FileRecord
  │     └─ For deleted files: delete_from_rag(rag_file_name)
  │
  ├─ GitHub Connector
  │     ├─ For each repo: compare(last_sha, HEAD)
  │     ├─ For new/modified files: fetch content → upload_to_rag() → store FileRecord
  │     └─ For removed files: delete_from_rag(rag_file_name)
  │
  └─ Save updated state → SYNC_STATE_GCS_URI
```

### Webhook Push Flow (Near Real-Time)

```
GitHub push event / SharePoint Graph notification
  │
  ▼
Cloud Run Service: python -m scheduler.webhook_server
  │
  ├─ POST /webhook/github
  │     └─ validate X-Hub-Signature-256 HMAC
  │     └─ identify affected repo + files
  │     └─ run incremental sync for that repo only
  │
  └─ POST /webhook/sharepoint
        └─ validate clientState secret
        └─ handle Graph subscription handshake (validationToken echo)
        └─ run incremental sync for affected site/drive
```

---

## Tool Connectors

### RAG Knowledge Base (`tools/rag/`)

| Tool | Description |
|------|-------------|
| `search_knowledge_base` | Semantic search across all indexed documents |
| `add_document_to_rag` | Index a single document (URL or GCS path) |
| `list_rag_documents` | List all indexed files in the corpus |
| `delete_rag_document` | Remove a file from the corpus |
| `upload_document` | Upload and index a document from the user |
| `list_my_documents` | List documents uploaded by the current user |
| `delete_my_document` | Delete a document the user uploaded |

**Config keys**: `corpus`, `embedding_model`, `chunk_size` (512), `chunk_overlap` (100), `similarity_top_k` (10), `vector_distance_threshold` (0.6)

---

### Gmail (`tools/google/gmail_tool.py`)
Uses Gmail API with a service account and domain-wide delegation (DWD).

| Tool | Description |
|------|-------------|
| `search_gmail` | Search messages using Gmail search syntax |
| `get_gmail_message` | Retrieve full message body by ID |

**Auth**: Service account JSON key stored in GCS, impersonates `user_email` via DWD.

---

### Google Drive (`tools/google/gdrive_tool.py`)

| Tool | Description |
|------|-------------|
| `search_gdrive` | Full-text search across Drive files |
| `get_gdrive_file_content` | Retrieve file content (max 50 K chars) |

---

### Gemini Enterprise (`tools/google/gemini_connector_tool.py`)

| Tool | Description |
|------|-------------|
| `search_gemini_connectors` | Search across all Gemini Enterprise connected sources |

---

### GitHub (`tools/github/github_tool.py`)
Uses PyGithub. Required PAT scopes: `repo` (read), `read:org`.

| Tool | Description |
|------|-------------|
| `list_github_repos` | List all repos in the configured org |
| `get_github_repository` | Repo metadata, branches, stats |
| `list_github_commits` | Commit history with filters |
| `get_github_commit` | Full commit with file diffs |
| `list_github_pull_requests` | PR listing by state/base branch |
| `get_github_pull_request` | Full PR + reviews + comments |
| `search_github_issues` | Search issues with GitHub syntax |
| `get_github_issue` | Full issue detail |
| `search_github_code` | Code search across repositories |
| `get_github_file_content` | Read a file at a specific branch/SHA |

---

### Jira (`tools/atlassian/jira_tool.py`)

| Tool | Description |
|------|-------------|
| `search_jira` | Query issues using JQL |
| `get_jira_issue` | Full issue detail with comments |

---

### Confluence (`tools/atlassian/confluence_tool.py`)

| Tool | Description |
|------|-------------|
| `search_confluence` | CQL search across spaces |
| `get_confluence_page` | Fetch page text (max 50 K chars) |

---

### SharePoint (`tools/microsoft/sharepoint_tool.py`)
Uses Microsoft Graph API with Azure AD app-only auth (MSAL).

| Tool | Description |
|------|-------------|
| `list_sharepoint_sites` | All accessible SharePoint sites |
| `get_sharepoint_site` | Site metadata |
| `list_sharepoint_drives` | Document libraries on a site |
| `list_sharepoint_drive_items` | Files and folders in a library |
| `search_sharepoint_files` | File search within a site |
| `get_sharepoint_file_content` | File text content (max 50 K chars) |
| `get_sharepoint_file_metadata` | File properties and timestamps |
| `list_sharepoint_lists` | SharePoint lists on a site |
| `get_sharepoint_list_items` | Query list items with OData filter |
| `search_sharepoint` | Full-text search across all SharePoint |
| `list_sharepoint_pages` | Modern pages on a site |
| `get_sharepoint_page` | Page text content |

**Config keys**: `tenant_id`, `client_id`, `client_secret`, `site_url`, `search_region` (`NAM`/`EUR`/`APC`)

---

### A2A Sub-Agents (`tools/a2a/a2a_tools.py`)

| Tool | Description |
|------|-------------|
| `call_crm_agent` | Delegate CRM operations to the HubSpot CRM Agent |
| `call_enrichment_agent` | Delegate company/contact enrichment to the Enrichment Agent |
| `call_web_scraper_agent` | Delegate web scraping + RAG indexing to the Web Scraper Agent |

---

## Dynamic Configuration System

The agent loads configuration from a single JSON file in GCS (`tools_config.json`), cached in-memory with a **60-second TTL**. Config changes take effect within 1 minute of upload — no redeployment needed.

### Config File Structure

```json
{
  "tools": {
    "rag": {
      "enabled": true,
      "config": {
        "corpus": "projects/PROJECT_ID/locations/us-central1/ragCorpora/CORPUS_ID",
        "embedding_model": "publishers/google/models/text-embedding-004",
        "chunk_size": 512,
        "chunk_overlap": 100,
        "similarity_top_k": 10,
        "vector_distance_threshold": 0.6
      }
    },
    "sharepoint": {
      "enabled": true,
      "config": {
        "tenant_id": "YOUR_AZURE_TENANT_ID",
        "client_id": "YOUR_APP_CLIENT_ID",
        "client_secret": "env:SHAREPOINT_CLIENT_SECRET",
        "site_url": "https://your-org.sharepoint.com/sites/Engineering",
        "search_region": "APC"
      }
    },
    "github": {
      "enabled": true,
      "config": {
        "token": "env:GITHUB_TOKEN",
        "default_org": "your-github-org",
        "default_repo": "your-github-org/main-repo"
      }
    },
    "gmail": {
      "enabled": false,
      "config": {
        "service_account_key_gcs_uri": "gs://your-bucket/sa-key.json",
        "user_email": "admin@your-org.com"
      }
    },
    "jira": {
      "enabled": false,
      "config": {
        "url": "https://your-org.atlassian.net",
        "username": "admin@your-org.com",
        "api_token": "env:JIRA_API_TOKEN"
      }
    },
    "confluence": {
      "enabled": false,
      "config": {
        "url": "https://your-org.atlassian.net/wiki",
        "username": "admin@your-org.com",
        "api_token": "env:CONFLUENCE_API_TOKEN"
      }
    }
  },
  "prompt": {
    "source": "gcs",
    "gcs_uri": "gs://your-bucket/knowledge-iq/prompt.txt"
  }
}
```

**Secrets pattern**: Any config value prefixed with `"env:VAR_NAME"` is resolved at load time from the Agent Engine's runtime environment. This keeps secrets out of GCS while centralising non-secret config there.

---

## Sync Service

The scheduler keeps the RAG corpus up to date via incremental (delta) syncs against SharePoint and GitHub.

### Delta Strategies

| Source | Strategy |
|--------|----------|
| SharePoint | Graph API `GET /drives/{id}/root/delta` with `@odata.deltaLink` per drive. `410 Gone` triggers full resync. |
| GitHub | HEAD SHA per repo stored in state. Uses `repo.compare(last_sha, head_sha)` for incremental diffs; full tree crawl on first run. |

### Supported File Types for Indexing

`.pdf`, `.docx`, `.pptx`, `.txt`, `.md`, `.rst`, `.html`, `.htm`, `.json`, `.py`, `.sql`

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11 – 3.12 | Runtime |
| [uv](https://docs.astral.sh/uv/) | latest | Package manager |
| gcloud CLI | latest | GCP operations |
| Docker | latest | Sync service image build |

**GCP APIs to enable:**

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  storage.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  --project=YOUR_PROJECT_ID
```

---

## Local Development Setup

```bash
# 1. Enter the agent directory
cd new_folder_structure/agents/knowledge-iq

# 2. Install dependencies
uv sync
uv pip install -e ../../shared   # editable stratova_shared

# 3. Create env file
cp enterpriseGPT/.env enterpriseGPT/.env.local
# Edit with your GCP project, GCS bucket, corpus IDs

# 4. Create and upload config
cp enterpriseGPT/config/tools_config.example.json enterpriseGPT/config/tools_config.json
# Edit with connector credentials (use "env:VAR_NAME" for secrets)
uv run python enterpriseGPT/deploy/scripts/upload_config.py

# 5. (Optional) Customise the prompt
cp enterpriseGPT/config/prompt.example.txt enterpriseGPT/config/prompt.txt
uv run python enterpriseGPT/deploy/scripts/upload_prompt.py

# 6. Run locally with ADK dev UI
# IMPORTANT: run from parent of enterpriseGPT/, not inside it
NEW_ROOT=/path/to/new_folder_structure
AGENT=$NEW_ROOT/agents/knowledge-iq/enterpriseGPT
VENV=$NEW_ROOT/agents/knowledge-iq/.venv

PYTHONPATH="$AGENT:$NEW_ROOT" $VENV/bin/adk web $NEW_ROOT/agents/knowledge-iq --port 8082
# Open http://127.0.0.1:8082 — select 'enterpriseGPT'
```

> **Important**: ADK web requires pointing to the **parent** of the agent folder (`knowledge-iq/`), not inside `enterpriseGPT/` itself. The agent name in the UI matches the folder name.

---

## Deploying the Agent

### Option A — Central Deploy Script (Recommended)

```bash
# From new_folder_structure/
export GCP_PROJECT=ninth-archway-496404-s2
export GCS_BUCKET=ninth-archway-496404-s2-knowledge-iq
./deployment/deploy_agent.sh
```

This calls `enterpriseGPT/deploy/deploy_full.py` which handles all 5 phases:
1. Enable required GCP APIs
2. Create GCS bucket + Artifact Registry
3. Create (or reuse) Vertex AI RAG corpus
4. Upload `tools_config.json` and `prompt.txt` to GCS
5. Deploy agent to Vertex AI Agent Engine + register with Gemini Enterprise

### Option B — Direct Python Deploy

```bash
cd enterpriseGPT/deploy
python deploy_full.py
```

**Environment variables required:**

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
export STAGING_BUCKET=gs://your-bucket
export TOOLS_CONFIG_GCS_URI=gs://your-bucket/knowledge-iq/tools_config.json
export PROMPT_GCS_URI=gs://your-bucket/knowledge-iq/prompt.txt
```

---

## Deploying the Sync Service

```bash
# From new_folder_structure/
export GCP_PROJECT=ninth-archway-496404-s2
export GCS_BUCKET=ninth-archway-496404-s2-knowledge-iq
./deployment/deploy_cloudrun.sh --scheduler
```

Or directly:
```bash
bash enterpriseGPT/deploy/sync_deploy.sh
```

This deploys:
1. **Cloud Run Job** (`knowledge-iq-sync-job`) — hourly cron via Cloud Scheduler
2. **Cloud Run Service** (`knowledge-iq-sync-webhook`) — always-on webhook receiver

```bash
# Run sync immediately after deploy
gcloud run jobs execute knowledge-iq-sync-job \
  --project=your-project-id \
  --region=us-central1
```

---

## Setting Up Gemini AI Enterprise (Console UI)

1. GCP Console → **Vertex AI** → **Agent Builder** → **Apps** → **+ Create app**
2. Select **Conversational agent**, enter app name `Knowledge IQ`
3. Navigate to **Vertex AI** → **Agent Engine** → find your deployed agent
4. Copy the resource name: `projects/PROJECT_ID/locations/LOCATION/reasoningEngines/ENGINE_ID`
5. In Agent Builder app → **Configurations** → paste the resource name under **Agent**
6. Grant **Vertex AI User** role to the Gemini service account: `service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com`
7. **Publish** → select target audience → confirm

---

## Runtime Operations (No Restart Required)

All changes below take effect within **60 seconds** (one TTL cycle) without redeploying.

### Enable / Disable a Tool

```bash
# Edit enterpriseGPT/config/tools_config.json — set "enabled": true/false
uv run python enterpriseGPT/deploy/scripts/upload_config.py
```

### Update the System Prompt

```bash
# Edit enterpriseGPT/config/prompt.txt
# Keep {tool_status} and {current_datetime} placeholders
uv run python enterpriseGPT/deploy/scripts/upload_prompt.py
```

### Update Agent Code

```bash
cd enterpriseGPT/deploy
python update_agent.py
```

---

## Environment Variables Reference

### Agent Runtime (Vertex AI Agent Engine)

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Yes | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | No | Region (default: `us-central1`) |
| `GOOGLE_GENAI_USE_VERTEXAI` | Yes | Must be `1` |
| `TOOLS_CONFIG_GCS_URI` | Yes | GCS URI for `tools_config.json` |
| `PROMPT_GCS_URI` | No | GCS URI for `prompt.txt` |
| `CONFIG_CACHE_TTL_SECONDS` | No | Config cache TTL in seconds (default: `60`) |
| `RAG_CORPUS` | Yes | Vertex AI RAG corpus resource name |
| `RAG_LOCATION` | No | RAG corpus region (default: `us-central1`) |
| `STAGING_BUCKET` | Yes | GCS bucket for ADK wheel staging |

**Tool secret env vars** (used via `"env:VAR_NAME"` in config):

| Variable | Tool |
|----------|------|
| `GITHUB_TOKEN` | GitHub PAT |
| `JIRA_API_TOKEN` | Atlassian API token |
| `CONFLUENCE_API_TOKEN` | Atlassian API token |
| `SHAREPOINT_CLIENT_SECRET` | Azure AD app secret |

### Sync Service (Cloud Run Job + Webhook)

| Variable | Required | Description |
|----------|----------|-------------|
| `TOOLS_CONFIG_GCS_URI` | Yes | Shared with agent — loads SP/GH credentials |
| `RAG_CORPUS` | Yes | Vertex AI corpus resource name |
| `SYNC_STATE_GCS_URI` | Yes | GCS path for sync state JSON |
| `SYNC_SHAREPOINT_SITES` | No | Comma-separated site URLs |
| `SYNC_SP_CLIENT_STATE` | No | Graph webhook validation secret |
| `SYNC_GITHUB_REPOS` | No | Comma-separated `owner/repo` slugs |
| `SYNC_GITHUB_FILE_EXTS` | No | Comma-separated extensions to index |
| `SYNC_GITHUB_WEBHOOK_SECRET` | No | HMAC secret for GitHub push events |
| `SYNC_SCHEDULE` | No | Cron schedule (default: `0 * * * *`) |
| `GCP_PROJECT` | Yes | GCP project ID (for deploy scripts) |
| `GCP_REGION` | No | GCP region (default: `us-central1`) |
