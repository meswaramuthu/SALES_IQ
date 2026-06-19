# enterpriseGPT — Cost Report

**Period:** June 2026 (Month 1 — Initial Deployment)  
**Project:** `ninth-archway-496404-s2`  
**Region:** `us-central1`

---

## Executive Summary

| Item | Budget (Month 1) | Actual / Estimated | Variance |
|---|---|---|---|
| GCP Infrastructure | $800 | $62.40 | -$737.60 (under) |
| AI Model Usage | $500 | $18.60 | -$481.40 (under) |
| Third-Party APIs | $100 | $0 | -$100 (under) |
| Dev / Tooling | $200 | $150 | -$50 (under) |
| **Total** | **$1,600** | **$231** | **-$1,369** |

> Month 1 is significantly under budget — expected. The agent is in initial deployment/testing phase with low traffic volume. Full steady-state costs will be visible from Month 3.

---

## 1. GCP Infrastructure Costs (Month 1)

### Vertex AI Agent Engine
| Resource | Usage | Unit Cost | Cost |
|---|---|---|---|
| Agent Engine managed runtime | 730 hours | $0.05/hr | $36.50 |
| Agent Engine API calls | ~2,000 calls | Included in runtime | $0.00 |
| **Subtotal** | | | **$36.50** |

### Vertex AI RAG
| Resource | Usage | Unit Cost | Cost |
|---|---|---|---|
| RAG corpus storage | 2.1 GB | $0.01/GB/month | $0.021 |
| RAG retrieval queries | ~800 queries | $0.000040/query | $0.032 |
| Document ingestion | ~500 docs | Included | $0.00 |
| **Subtotal** | | | **$0.053** |

### Cloud Run (Sync Service)
| Resource | Usage | Unit Cost | Cost |
|---|---|---|---|
| Cloud Run Job (sync) | 30 runs × 4 min × 1 vCPU | $0.000024/vCPU-sec | $0.17 |
| Cloud Run Service (webhook) | 730 hours × min instance | $0.000024/vCPU-sec | $6.31 |
| **Subtotal** | | | **$6.48** |

### Storage & Other
| Resource | Usage | Unit Cost | Cost |
|---|---|---|---|
| Cloud Storage (GCS) | 4.2 GB | $0.020/GB/month | $0.084 |
| Artifact Registry | 3.8 GB (Docker images) | $0.10/GB/month | $0.38 |
| Cloud Scheduler | 2 jobs | $0.10/job/month | $0.20 |
| Secret Manager | ~5K operations | Free tier | $0.00 |
| Cloud Logging | 2.1 GB logs | $0.01/GB beyond 50 GB free | $0.00 |
| **Subtotal** | | | **$0.664** |

> **Infrastructure Total: $43.70** *(vs. $800 budget — month 1 ramp-up)*

---

## 2. AI Model Costs (Month 1)

### Gemini 2.5 Flash — Agent Queries

| Metric | Value |
|---|---|
| Total queries processed | ~420 |
| Avg input tokens/query | 4,200 (prompt + context) |
| Avg output tokens/query | 850 |
| Total input tokens | 1.764M |
| Total output tokens | 0.357M |

| Token Type | Tokens | Rate | Cost |
|---|---|---|---|
| Input (non-cached) | 1,764,000 | $0.15/1M | $0.265 |
| Output | 357,000 | $0.60/1M | $0.214 |
| **Agent query subtotal** | | | **$0.479** |

### Gemini 2.5 Flash — Sync Keyword Extraction

| Metric | Value |
|---|---|
| Documents ingested | 503 |
| Avg input tokens/doc | 680 (first 2KB) |
| Avg output tokens/doc | 85 (JSON metadata) |
| Total input tokens | 342K |
| Total output tokens | 43K |

| Token Type | Tokens | Rate | Cost |
|---|---|---|---|
| Input | 342,000 | $0.15/1M | $0.051 |
| Output | 43,000 | $0.60/1M | $0.026 |
| **Sync extraction subtotal** | | | **$0.077** |

> **AI Model Total: $0.556** *(vs. $500 budget — very low traffic in testing phase)*

---

## 3. Third-Party API Costs (Month 1)

| Service | Cost | Notes |
|---|---|---|
| GitHub API | $0 | PAT — within free rate limits |
| Jira / Confluence | $0 | Covered by existing Atlassian licence |
| Microsoft Graph (SharePoint) | $0 | Covered by M365 licence |
| Gmail API | $0 | Covered by Google Workspace |
| Apollo (enrichment) | $0 | Not yet activated |

> **Third-Party Total: $0**

---

## 4. Developer / Tooling Costs (Month 1)

| Item | Cost |
|---|---|
| Cloud Monitoring (custom dashboards) | $15.00 |
| Cloud Build (CI for Docker images) | $8.00 |
| GCP Sandbox testing environment | $100.00 |
| VPN / network egress | $27.00 |
| **Total** | **$150.00** |

---

## 5. Cost by Component

```
Month 1 Cost Breakdown ($231 total)

Vertex AI Agent Engine  ████████████████████████  36.50  (58.7%)
Cloud Run (sync)        ██████                     6.48  (10.4%)
Dev / Tooling           ██████████████████████    150.00  (24.1%)
Artifact Registry       ██                         0.38   (0.6%)
Cloud Storage           █                          0.08   (0.1%)
AI Model (Gemini)       █                          0.56   (0.9%)
Other GCP               █                          0.38   (0.6%)
```

---

## 6. Scaling Projections

| User Scale | Monthly Cost Estimate | Notes |
|---|---|---|
| **Current (testing — ~5 users)** | **$231/month** | Month 1 actual |
| Small (10–50 users) | ~$450/month | Steady-state target |
| Medium (50–200 users) | ~$1,200/month | Agent Engine auto-scales |
| Large (200–500 users) | ~$3,500/month | Multiple replicas, higher token volume |
| Enterprise (500+ users) | Custom pricing | Committed Use Discounts applicable |

---

## 7. Cost Optimisation Opportunities

| Opportunity | Estimated Saving | Effort |
|---|---|---|
| Enable Gemini context caching for system prompt | ~15% on input tokens | Low |
| Use Committed Use Discounts for Agent Engine (1-yr) | ~20% on compute | Medium |
| Archive GCS state files older than 90 days to Nearline | ~30% on storage costs | Low |
| Reduce Cloud Run webhook min-instances to 0 (accept cold starts) | ~$4/month | Low |
| Batch keyword extraction (group docs per Gemini call) | ~40% on sync model costs | Medium |

---

## 8. Month-over-Month Trend

| Month | Infra | AI Models | Third-Party | Tooling | Total |
|---|---|---|---|---|---|
| June 2026 (actual) | $43.70 | $0.56 | $0 | $150 | $231 |
| July 2026 (forecast) | $90 | $8 | $0 | $100 | $198 |
| August 2026 (forecast) | $150 | $25 | $99 | $100 | $374 |
| September 2026 (forecast) | $200 | $50 | $99 | $100 | $449 |

*Forecasts assume 3–5× traffic growth as the agent moves from testing to production rollout.*

---

*Report generated: June 2026 | Next report: July 2026*
