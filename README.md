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

## Getting Started

Each agent has its own `pyproject.toml` and `Makefile`. Start with the agent you own:

```bash
cd agents/knowledge-iq/enterpriseGPT
cp config/prompt.example.txt config/prompt.txt
cp config/tools_config.example.json config/tools_config.json
# populate .env from GCP Secret Manager
make run
```

For tool server development:

```bash
cd tools/mcp_servers/rag
docker build -t rag-mcp . && docker run -p 8080:8080 rag-mcp
```

---

## Contact

**Stratova AI Pte Ltd** · stratova.ai / laabu.ai  
CTO: Manivannan — ms@stratova.ai
