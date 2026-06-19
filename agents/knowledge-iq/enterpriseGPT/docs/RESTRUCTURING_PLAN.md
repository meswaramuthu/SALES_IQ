# Plan: Copy Knowledge IQ into new_folder_structure

## Context

The user is standardising the repo layout using a new hierarchical template defined in `new_folder_structure/`. The template mandates standardised subdirectories per agent: `config/`, `deploy/`, `docs/`, `evaluation/`, `memory/`, `scheduler/`, plus `pyproject.toml` and `.env`.

The goal is to copy all Knowledge IQ agent code into:
```
new_folder_structure/agents/knowledge-iq/enterpriseGPT/
```
with tool modules promoted to the top-level `tools/` folder organised by vendor/category.

**This is a copy operation** — originals in `agents/knowledge-iq/` remain untouched.

---

## Key Structural Decisions

1. **No `knowledge_iq/` package wrapper** — agent files (agent.py, config.py, prompts.py, etc.) go directly at the `enterpriseGPT/` root level
2. **No `shared_libraries/` at enterpriseGPT root** — `gcs_utils.py` moves to `tools/utils/`
3. **Tool files** (currently in `knowledge_iq/tools/`) go into the top-level `new_folder_structure/tools/` with vendor/category subfolders
4. **`stratova_shared/` is NOT copied** — it stays in `agents/shared/stratova_shared/`

---

## File Mapping

### Agent core files → `enterpriseGPT/` root

| Source (`agents/knowledge-iq/knowledge_iq/`) | Destination |
|---|---|
| `__init__.py` | `enterpriseGPT/__init__.py` |
| `agent.py` | `enterpriseGPT/agent.py` |
| `agent_engine_app.py` | `enterpriseGPT/agent_engine_app.py` |
| `config.py` | `enterpriseGPT/config.py` |
| `prompts.py` | `enterpriseGPT/prompts.py` |
| `shared_libraries/gcs_utils.py` | `tools/utils/gcs_utils.py` (not at enterpriseGPT root) |

### Tool files → `tools/` with category subfolders

| Source (`knowledge_iq/tools/`) | Destination (`new_folder_structure/tools/`) |
|---|---|
| `registry.py` | `tools/registry.py` |
| `rag_tool.py` | `tools/rag/rag_tool.py` |
| `user_rag_tool.py` | `tools/rag/user_rag_tool.py` |
| `gmail_tool.py` | `tools/google/gmail_tool.py` |
| `gdrive_tool.py` | `tools/google/gdrive_tool.py` |
| `gemini_connector_tool.py` | `tools/google/gemini_connector_tool.py` |
| `jira_tool.py` | `tools/atlassian/jira_tool.py` |
| `confluence_tool.py` | `tools/atlassian/confluence_tool.py` |
| `sharepoint_tool.py` | `tools/microsoft/sharepoint_tool.py` |
| `github_tool.py` | `tools/github/github_tool.py` |
| `a2a_tools.py` | `tools/a2a/a2a_tools.py` |

### Standard template folders

| Source (`agents/knowledge-iq/`) | Destination |
|---|---|
| `config/` (all 4 files) | `enterpriseGPT/config/` |
| `deployment/deploy_full.py` | `enterpriseGPT/deploy/deploy_full.py` |
| `deployment/deploy.py` | `enterpriseGPT/deploy/deploy.py` |
| `deployment/update_agent.py` | `enterpriseGPT/deploy/update_agent.py` |
| `deployment/run.py` | `enterpriseGPT/deploy/run.py` |
| `deployment/deployment_state.json` | `enterpriseGPT/deploy/deployment_state.json` |
| `scripts/setup_corpus.py` | `enterpriseGPT/deploy/scripts/setup_corpus.py` |
| `scripts/setup_connector.py` | `enterpriseGPT/deploy/scripts/setup_connector.py` |
| `scripts/upload_config.py` | `enterpriseGPT/deploy/scripts/upload_config.py` |
| `scripts/upload_prompt.py` | `enterpriseGPT/deploy/scripts/upload_prompt.py` |
| `sync/deploy.sh` | `enterpriseGPT/deploy/sync_deploy.sh` |
| `sync/Dockerfile` | `enterpriseGPT/deploy/sync_Dockerfile` |
| `sync/` (all except deploy.sh + Dockerfile) | `enterpriseGPT/scheduler/` |
| `README.md` | `enterpriseGPT/docs/README.md` |
| `agent-card/agent-card.json` | `enterpriseGPT/agent-card/agent-card.json` |
| `demo-documents/` | `enterpriseGPT/evaluation/demo-documents/` |
| `memory/` | `enterpriseGPT/memory/` |
| `pyproject.toml` | `enterpriseGPT/pyproject.toml` |
| `.env.example` | `enterpriseGPT/.env` |
| `Makefile` | `enterpriseGPT/Makefile` |
| `uv.lock` | `enterpriseGPT/uv.lock` |

---

## Final Target Structure

```
new_folder_structure/
├── agents/
│   └── knowledge-iq/
│       └── enterpriseGPT/
│           ├── __init__.py
│           ├── agent.py
│           ├── agent_engine_app.py
│           ├── config.py
│           ├── prompts.py
│           ├── config/
│           │   ├── prompt.txt
│           │   ├── prompt.example.txt
│           │   ├── tools_config.json
│           │   └── tools_config.example.json
│           ├── deploy/
│           │   ├── deploy_full.py
│           │   ├── deploy.py
│           │   ├── update_agent.py
│           │   ├── run.py
│           │   ├── deployment_state.json
│           │   ├── sync_deploy.sh
│           │   ├── sync_Dockerfile
│           │   └── scripts/
│           │       ├── setup_corpus.py
│           │       ├── setup_connector.py
│           │       ├── upload_config.py
│           │       └── upload_prompt.py
│           ├── agent-card/
│           │   └── agent-card.json
│           ├── docs/
│           │   └── README.md
│           ├── evaluation/
│           │   └── demo-documents/   # 9 sample files
│           ├── memory/
│           │   └── project_rag_sync_service.md
│           ├── scheduler/            # sync service (Cloud Run Job + Webhook)
│           │   ├── __init__.py
│           │   ├── config.py
│           │   ├── state.py
│           │   ├── ingestion.py
│           │   ├── keyword_extractor.py
│           │   ├── job.py
│           │   ├── webhook_server.py
│           │   ├── requirements.txt
│           │   └── connectors/
│           │       ├── __init__.py
│           │       ├── base.py
│           │       ├── sharepoint.py
│           │       └── github.py
│           ├── .env
│           ├── Makefile
│           ├── pyproject.toml
│           └── uv.lock
├── deployment/
│   ├── deploy_agent.sh               # triggers full agent deployment (Agent Engine + RAG + GCS config)
│   └── deploy_cloudrun.sh            # deploys Cloud Run services: MCP tools + scheduler jobs
└── tools/
    ├── registry.py
    ├── utils/
    │   ├── __init__.py
    │   └── gcs_utils.py             # from knowledge_iq/shared_libraries/
    ├── rag/
    │   ├── __init__.py
    │   ├── rag_tool.py
    │   └── user_rag_tool.py
    ├── google/
    │   ├── __init__.py
    │   ├── gmail_tool.py
    │   ├── gdrive_tool.py
    │   └── gemini_connector_tool.py
    ├── atlassian/
    │   ├── __init__.py
    │   ├── jira_tool.py
    │   └── confluence_tool.py
    ├── microsoft/
    │   ├── __init__.py
    │   └── sharepoint_tool.py
    ├── github/
    │   ├── __init__.py
    │   └── github_tool.py
    └── a2a/
        ├── __init__.py
        └── a2a_tools.py
```

---

## Top-Level Deployment Scripts (new files to create)

### `deployment/deploy_agent.sh`
Central entry point to deploy the full Knowledge IQ agent stack:
- Sets required env vars (project, region, bucket)
- Calls `agents/knowledge-iq/enterpriseGPT/deploy/deploy_full.py` which handles:
  - GCP infrastructure setup (Artifact Registry, GCS bucket, Service Account)
  - Vertex AI RAG corpus creation
  - Config + prompt upload to GCS
  - Agent Engine deployment
  - Gemini Enterprise connector registration

### `deployment/deploy_cloudrun.sh`
Central entry point to deploy all Cloud Run services:
- **Scheduler jobs**: calls `agents/knowledge-iq/enterpriseGPT/deploy/sync_deploy.sh` which deploys the Cloud Run Job (cron sync) and Cloud Run Service (webhook receiver)
- **MCP tools** (future): placeholder section to deploy any MCP tool servers as Cloud Run services when they are added

---

## Import Path Note

Moving files changes Python package paths. The copied code has stale references that would need updating in a follow-on task when this structure is used for execution:

| Old import | Will need to become |
|---|---|
| `from knowledge_iq.config import get_config` | `from config import get_config` |
| `from knowledge_iq.tools.registry import get_all_tools` | `from tools.registry import get_all_tools` |
| `from knowledge_iq.tools.gmail_tool import ...` | `from tools.google.gmail_tool import ...` |
| `from knowledge_iq.shared_libraries.gcs_utils import ...` | `from tools.utils.gcs_utils import ...` |

**This plan copies files as-is without modifying imports.**

---

## Implementation Steps

1. Create directory skeleton — all subdirs under `enterpriseGPT/` and all `tools/` category folders (rag, google, atlassian, microsoft, github, a2a, utils)
2. Copy agent core files (agent.py, agent_engine_app.py, config.py, prompts.py, __init__.py) → `enterpriseGPT/` root
3. Copy `knowledge_iq/shared_libraries/gcs_utils.py` → `tools/utils/gcs_utils.py`
4. Copy `knowledge_iq/tools/registry.py` → `tools/registry.py`
5. Copy each tool file into its category folder + create `__init__.py` per category
6. Copy `config/` → `enterpriseGPT/config/`
7. Copy deployment scripts → `enterpriseGPT/deploy/`; setup scripts → `enterpriseGPT/deploy/scripts/`
8. Copy `sync/deploy.sh` → `enterpriseGPT/deploy/sync_deploy.sh`; `sync/Dockerfile` → `enterpriseGPT/deploy/sync_Dockerfile`
9. Copy `sync/` (rest) → `enterpriseGPT/scheduler/`
10. Copy `README.md` → `enterpriseGPT/docs/README.md`; `agent-card/` → `enterpriseGPT/docs/agent-card/`
11. Copy `demo-documents/` → `enterpriseGPT/evaluation/demo-documents/`
12. Copy `memory/` → `enterpriseGPT/memory/`
13. Copy `agent-card/` → `enterpriseGPT/agent-card/` (at enterpriseGPT root, outside docs/)
14. Copy `pyproject.toml`, `.env.example` (as `.env`), `Makefile`, `uv.lock` to `enterpriseGPT/`
15. **Create** `deployment/deploy_agent.sh` — skeleton script that calls `enterpriseGPT/deploy/deploy_full.py` with env var setup
16. **Create** `deployment/deploy_cloudrun.sh` — skeleton script that calls `enterpriseGPT/deploy/sync_deploy.sh` + placeholder section for future MCP tools

---

## Verification

```bash
# Verify agent core at root (no knowledge_iq/ wrapper)
ls new_folder_structure/agents/knowledge-iq/enterpriseGPT/agent.py

# Verify categorised tools
ls new_folder_structure/tools/rag/
ls new_folder_structure/tools/google/
ls new_folder_structure/tools/atlassian/
ls new_folder_structure/tools/utils/gcs_utils.py

# Verify scheduler has sync files
ls new_folder_structure/agents/knowledge-iq/enterpriseGPT/scheduler/job.py

# Total file count
find new_folder_structure/ -type f | wc -l
```
