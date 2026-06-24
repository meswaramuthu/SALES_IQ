# Laabu.ai — The Autonomous AI Workforce

> One Knowledge IQ Leader · Six Dual-Persona IQ Orchestrators · Subagents & Tools  
> Built on Gemini Enterprise Agent Platform · Google Cloud

---

## What is Laabu?

**Laabu.ai** is an interconnected AI workforce: one leader agent and six specialist IQ agents that share enterprise memory, governance, and accountability. Unlike isolated AI assistants, Laabu agents collaborate, hand off work, and execute end-to-end business processes together.

### The Operating Model

**LAABU (Knowledge IQ)** is the enterprise memory and central orchestrator. It holds context, enforces policy, and routes work to six IQ orchestrators. Every specialist IQ calls LAABU for context and grounding — no agent queries enterprise data directly.

| Agent | Name | Function | Persona |
|-------|------|----------|---------|
| **LAABU** | Knowledge IQ | Enterprise memory · RAG · orchestration | Public Knowledge Bot / Enterprise Search Brain |
| **RIVO** | Marketing IQ | Demand generation · content studio · campaigns | Brand Engagement Bot / Campaign Intelligence Assistant |
| **JANY** | Support IQ | Omnichannel support · IT helpdesk · agent assist | Omnichannel Service Bot / Customer Success Copilot |
| **AURA** | Sales IQ | Prospect to close · revenue intelligence · coaching | Digital Sales Representative / Sales Intelligence Agent |
| **CRIZ** | Admin IQ | Contracts · travel · procurement · executive assist | Partner & Vendor Concierge / Operations Assistant |
| **FINA** | Finance IQ | AP/AR automation · reporting · forecasting | Billing & Collections Bot / Financial Intelligence Agent |
| **AUGY** | HR IQ | Recruitment · onboarding · policy · L&D | Talent Acquisition Bot / Employee Success Agent |

Each IQ runs a **dual persona**: an external customer-facing agent and an internal employee-facing copilot.

### Cross-Agent Orchestration Flow

```
Demand   → RIVO   runs outbound campaigns; qualified leads surfaced
Engage   → JANY   captures intent across any channel
Convert  → AURA   qualifies, proposes, closes; sets deal_won
Execute  → CRIZ   generates contract + onboarding; FINA invoices & collects
Resource → CRIZ   emits new_hire; AUGY runs talent acquisition & onboarding
Learn    → LAABU  captures every workflow outcome into enterprise memory
```

### Platform

- **Runtime**: Vertex AI Agent Engine (Gemini Enterprise Agent Platform)
- **Tools**: Cloud Run MCP servers
- **Framework**: Google Cloud Well-Architected Framework (all five pillars)
- **Governance**: RBAC, DLP, HITL gates on high-risk actions, Cloud Audit Logs

---

## Repository Structure

```
laabu-ai-app/
├── agents/                   ← Agent implementations (one folder per IQ)
│   └── knowledge-iq/         ← Knowledge IQ — LAABU (owned by Abdul)
│       └── enterpriseGPT/    ← The enterprise search / RAG agent
│           ├── agent.py                  ← Main ADK agent entrypoint
│           ├── agent_engine_app.py       ← Vertex AI Agent Engine wrapper
│           ├── prompts.py                ← System prompt definitions
│           ├── config.py                 ← Runtime configuration loader
│           ├── config/
│           │   ├── prompt.txt            ← Active agent system prompt
│           │   ├── prompt.example.txt    ← Reference prompt template
│           │   ├── tools_config.json     ← Which MCP tools are enabled
│           │   └── tools_config.example.json
│           ├── memory/                   ← Memory Bank state & schemas
│           ├── scheduler/                ← Background ingestion jobs
│           │   ├── job.py                ← Scheduler entrypoint
│           │   ├── ingestion.py          ← Document ingestion pipeline
│           │   ├── keyword_extractor.py  ← Keyword extraction for RAG
│           │   ├── state.py              ← Ingestion state tracking
│           │   ├── webhook_server.py     ← Webhook receiver for live updates
│           │   └── connectors/           ← Data source connectors
│           │       ├── base.py           ← Abstract connector interface
│           │       ├── github.py         ← GitHub connector
│           │       └── sharepoint.py     ← Microsoft SharePoint connector
│           ├── evaluation/               ← ADK eval scripts & test datasets
│           │   ├── run_eval.py           ← Evaluation runner
│           │   ├── conftest.py           ← Pytest configuration
│           │   └── test_cases/           ← Per-integration test JSON files
│           │       ├── rag.test.json
│           │       ├── atlassian.test.json
│           │       ├── github.test.json
│           │       ├── google.test.json
│           │       ├── sharepoint.test.json
│           │       ├── a2a.test.json
│           │       └── multi_tool.test.json
│           ├── deploy/                   ← Deployment scripts for this agent
│           │   ├── deploy.py             ← Standard deploy to Agent Engine
│           │   ├── deploy_full.py        ← Full deployment including setup
│           │   ├── update_agent.py       ← Update an existing deployed agent
│           │   ├── run.py                ← Local run helper
│           │   ├── sync_deploy.sh        ← Shell wrapper for synced deploy
│           │   ├── sync_Dockerfile       ← Dockerfile for sync container
│           │   └── scripts/              ← One-time setup scripts
│           │       ├── setup_corpus.py   ← Create Vertex AI RAG corpus
│           │       ├── setup_connector.py ← Configure data connectors
│           │       ├── upload_prompt.py  ← Push prompt to GCS
│           │       └── upload_config.py  ← Push tool config to GCS
│           ├── agent-card/
│           │   └── agent-card.json       ← A2A agent card (capability manifest)
│           ├── docs/                     ← Gate artifacts (design, budget, cost)
│           │   ├── design.md             ← ★ Gate 1: Agent design document
│           │   ├── budget.md             ← ★ Gate 1: Budget estimate
│           │   ├── cost_report.md        ← ★ Gate 3: Budget vs Actual (per deploy)
│           │   ├── implementation.md     ← Implementation notes
│           │   ├── sample_prompts.md     ← Example prompts for demos
│           │   ├── RESTRUCTURING_PLAN.md ← Architecture evolution notes
│           │   └── architecture.png      ← Architecture diagram
│           ├── pyproject.toml            ← Python package definition & deps
│           ├── uv.lock                   ← Locked dependency versions
│           └── Makefile                  ← Common dev commands
│
├── tools/                    ← Shared MCP tool servers (Cloud Run services)
│   ├── registry.py           ← Central tool registry (maps tool names → implementations)
│   ├── rag/                  ← Retrieval-Augmented Generation tool
│   │   ├── rag_tool.py       ← Corpus-level RAG (all enterprise docs)
│   │   └── user_rag_tool.py  ← User-scoped RAG (RBAC-filtered)
│   ├── atlassian/            ← Jira & Confluence integration
│   │   ├── jira_tool.py      ← Jira issue search, create, update
│   │   └── confluence_tool.py ← Confluence page read & search
│   ├── github/               ← GitHub integration
│   │   └── github_tool.py    ← Repo, PR, issue, and code search
│   ├── google/               ← Google Workspace integrations
│   │   ├── gmail_tool.py     ← Gmail read & send
│   │   ├── gdrive_tool.py    ← Google Drive file access
│   │   └── gemini_connector_tool.py ← Gemini Enterprise connector bridge
│   ├── microsoft/            ← Microsoft 365 integrations
│   │   └── sharepoint_tool.py ← SharePoint document access
│   ├── a2a/                  ← Agent-to-Agent communication
│   │   └── a2a_tools.py      ← A2A protocol tools (call other IQ agents)
│   ├── search/               ← Web search
│   │   └── google_search.py  ← Google Search grounding
│   ├── utils/                ← Shared utilities
│   │   ├── date_time.py      ← Date/time helpers
│   │   └── gcs_utils.py      ← Google Cloud Storage helpers
│   └── mcp_servers/          ← Standalone MCP server containers (deployed to Cloud Run)
│       ├── rag/              ← RAG MCP server
│       │   ├── server.py     ← FastMCP server exposing RAG tools
│       │   ├── Dockerfile
│       │   ├── requirements.txt
│       │   └── deploy.sh
│       ├── web/              ← Web search MCP server
│       │   ├── server.py
│       │   ├── Dockerfile
│       │   ├── requirements.txt
│       │   └── deploy.sh
│       └── google/           ← Google Workspace MCP servers
│           ├── email/        ← Gmail MCP server
│           ├── calendar/     ← Google Calendar MCP server
│           ├── session/      ← Session management MCP server
│           └── gemini_ds/    ← Gemini Data Store MCP server
│
├── deployment/               ← Top-level deployment automation
│   ├── deploy_agent.sh       ← Deploy an IQ agent to Vertex AI Agent Engine
│   └── deploy_cloudrun.sh    ← Deploy an MCP tool server to Cloud Run
│
└── docs/                     ← Project-level documentation
    └── Laabu_Master_Document_v1.docx  ← Full product whitepaper & architecture spec
```

---

## Key Design Decisions

**Integrations live once.** All tool implementations sit in `tools/` and are shared across every IQ agent. No duplication across agent folders.

**MCP servers are the tool boundary.** Each integration in `tools/mcp_servers/` is a self-contained Cloud Run service. Agents call tools over the MCP protocol — no direct library imports in agent code.

**Secrets never in code.** All `.env` files are gitignored. Secrets live in GCP Secret Manager and are pulled at runtime.

**Gate artifacts are mandatory.** `docs/design.md` and `docs/budget.md` are required before GCP access is granted. `docs/cost_report.md` must be submitted with every deployment PR.

---

## Branch Strategy & CI/CD

The CI/CD pipeline is the **only path to production**. No manual deployments. Every merge and deploy is auditable via GitHub.

### Branch flow

```
feature-xxx  →  PR  →  develop  →  PR  →  release  →  security scan  →  main
```

### Branch details

| Branch | Responsibility | GCP Environment | Gate |
|--------|---------------|-----------------|------|
| `main` | Production (stable, scanned) | — | Security scan must pass |
| `release` | Security testing | `release_project` | 1 approval required · releases the feature |
| `develop` | Deploy & Demo | `develop_project` | 1 approval required · creates PR to release |
| `feature-xxx` | Develop locally | `feature_project` | PR to develop |

### GitHub Actions workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `feature.yml` | Push to `feature-xxx` | Local development validation |
| `develop.yml` | Merge to `develop` | Deploy to demo environment |
| `release.yml` | Merge to `release` | Security scan before production |

### Budget controls

- A **GCP budget alert** (80% threshold + hard cap) is set per IQ agent before any workload runs.
- A **developer label** is applied to every GCP resource at creation so spend is tracked per person.
- A **Budget vs Actual report** (`docs/cost_report.md`) must be submitted with every deployment PR. Overruns require sign-off.

---

## Local Development — Running Agents with ADK Web

This section walks you through running any IQ agent on your local machine using the ADK web UI. Follow every step in order.

### GCP Project for Local Testing

All local development must use the shared development project:

```
GCP Project ID: development-local-500411
```

Request access from Abdul or Anshul if you do not have it yet. Do **not** use `ninth-archway-496404-s2` (production) for local runs.

---

### Step 1 — Prerequisites

Install the following tools before starting:

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11 or 3.12 | [python.org](https://www.python.org/downloads/) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Google Cloud SDK | latest | [cloud.google.com/sdk](https://cloud.google.com/sdk/docs/install) |
| Docker | latest | Required only if running MCP servers locally |

---

### Step 2 — Authenticate with Google Cloud

```bash
# Log in and set application default credentials
gcloud auth login
gcloud auth application-default login

# Set the local development project
gcloud config set project development-local-500411

# Verify
gcloud config get project
```

ADK and all Vertex AI calls pick up credentials from Application Default Credentials (ADC). The `gcloud auth application-default login` step is mandatory — the agent will fail to start without it.

---

### Step 3 — Clone the repo and navigate to your agent

```bash
git clone https://github.com/stratova-ai/laabu-ai-app.git
cd laabu-ai-app

# Navigate to your agent — example: Knowledge IQ
cd agents/knowledge-iq/enterpriseGPT
```

Each IQ agent lives in its own folder under `agents/`. The steps below use `knowledge-iq/enterpriseGPT` as the example — replace the path with your own agent folder.

---

### Step 4 — Copy the example config files

```bash
# Agent system prompt
cp config/prompt.example.txt config/prompt.txt

# Tool enablement config
cp config/tools_config.example.json config/tools_config.json
```

Edit `config/tools_config.json` to enable only the tools you need locally. Set `"enabled": true` for each tool you want to test and fill in the corresponding credentials. Leave everything else `false` to avoid dependency errors.

---

### Step 5 — Create your `.env` file

Create a `.env` file in the agent folder (it is gitignored — never commit it):

```bash
touch .env
```

Add the following variables to `.env`. Only the first three are required to start the agent; the rest depend on which tools you have enabled in `tools_config.json`:

```dotenv
# ── Required ────────────────────────────────────────────────
GOOGLE_CLOUD_PROJECT=development-local-500411
GOOGLE_CLOUD_LOCATION=us-central1
GCS_BUCKET=stratova-platform

# ── RAG (required if rag tool is enabled) ───────────────────
KNOWLEDGE_IQ_RAG_CORPUS=projects/development-local-500411/locations/us-central1/ragCorpora/YOUR_CORPUS_ID
RAG_LOCATION=us-central1

# ── GitHub (required if github tool is enabled) ──────────────
GITHUB_TOKEN=ghp_yourPersonalAccessToken

# ── Atlassian (required if jira/confluence tools are enabled) ─
JIRA_API_TOKEN=your_jira_api_token
CONFLUENCE_API_TOKEN=your_confluence_api_token

# ── Microsoft (required if sharepoint tool is enabled) ────────
SHAREPOINT_CLIENT_SECRET=your_client_secret

# ── Google Workspace (required if gmail/gdrive tools enabled) ─
GMAIL_SA_KEY_GCS_URI=gs://stratova-platform/creds/google-sa.json
GMAIL_USER_EMAIL=you@stratova.ai
```

Obtain the actual secret values from GCP Secret Manager in the `development-local-500411` project:

```bash
# Example — fetch a secret value
gcloud secrets versions access latest \
  --secret=GITHUB_TOKEN \
  --project=development-local-500411
```

---

### Step 6 — Install dependencies

```bash
# Install all runtime + dev dependencies
make dev

# Or directly with uv
uv sync --group dev
```

This installs the pinned versions from `uv.lock` into a local virtual environment managed by uv.

---

### Step 7 — Run the agent with ADK Web

```bash
# Using the Makefile shortcut
make web

# Or directly
uv run adk web
```

ADK Web starts a local UI at **http://localhost:8000**. Open it in your browser.

You will see:
- A chat interface to send prompts to the agent
- A tool call trace panel showing every tool the agent invokes
- A session panel to review conversation history

> **Note:** ADK Web loads your `.env` file automatically. If you change `.env`, restart the server.

---

### Step 8 — Select your agent in the UI

When the browser opens at `http://localhost:8000`:

1. Click the **agent selector** dropdown at the top of the chat panel
2. Select your agent (e.g. `knowledge_iq`)
3. Type a prompt and press **Enter**

The tool trace panel on the right shows every tool call in real time — useful for debugging which tools are being invoked and what they return.

---

### Step 9 — (Optional) Run MCP servers locally

If your agent calls MCP tool servers (RAG, Web scraper, Calendar, etc.) and you need to test those locally too, run them as Docker containers:

```bash
# Example — RAG MCP server
cd tools/mcp_servers/rag
docker build -t rag-mcp .
docker run -p 8080:8080 \
  -e GOOGLE_CLOUD_PROJECT=development-local-500411 \
  -e KNOWLEDGE_IQ_RAG_CORPUS=your_corpus_resource_name \
  -e RAG_LOCATION=us-central1 \
  rag-mcp

# Example — Web scraper MCP server
cd tools/mcp_servers/web
docker build -t web-mcp .
docker run -p 8081:8080 \
  -e GOOGLE_CLOUD_PROJECT=development-local-500411 \
  web-mcp
```

Update `config/tools_config.json` to point the MCP URL to `http://localhost:8080` (or whichever port you mapped) instead of the Cloud Run URL.

---

### Step 10 — Run evaluations

Once the agent responds correctly to manual prompts, run the eval suite:

```bash
make test

# Or target a specific connector's test cases
uv run pytest evaluation/ -v -k "rag"
uv run pytest evaluation/ -v -k "atlassian"
```

Eval results are written to `evaluation/` and must be committed with any deployment PR.

---

### Common issues

| Problem | Fix |
|---------|-----|
| `google.auth.exceptions.DefaultCredentialsError` | Run `gcloud auth application-default login` again |
| `PermissionDenied` on Vertex AI / GCS | Request access to `development-local-500411` |
| Agent starts but tools all fail | Check `.env` — missing or wrong secret values |
| `ModuleNotFoundError` | Run `make dev` to install dependencies |
| Port 8000 already in use | `uv run adk web --port 8001` |
| RAG corpus not found | Verify `KNOWLEDGE_IQ_RAG_CORPUS` in `.env` matches a corpus in `development-local-500411` |

---

## Getting Started (Quick Reference)

```bash
# 1. Authenticate
gcloud auth application-default login
gcloud config set project development-local-500411

# 2. Set up config
cd agents/knowledge-iq/enterpriseGPT
cp config/prompt.example.txt config/prompt.txt
cp config/tools_config.example.json config/tools_config.json

# 3. Create .env with GOOGLE_CLOUD_PROJECT=development-local-500411

# 4. Install and run
make dev
make web
# → open http://localhost:8000
```

For MCP tool server development:

```bash
cd tools/mcp_servers/rag
docker build -t rag-mcp . && docker run -p 8080:8080 -e GOOGLE_CLOUD_PROJECT=development-local-500411 rag-mcp
```

---

## Contact

**Stratova AI Pte Ltd** · stratova.ai / laabu.ai  
CTO: Manivannan — ms@stratova.ai
