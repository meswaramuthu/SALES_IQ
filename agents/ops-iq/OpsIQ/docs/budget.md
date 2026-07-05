# OpsIQ — Project Budget

## Overview

This document outlines the approved budget for building, deploying, and operating the OpsIQ (GCP Resource Monitoring) agent on Google Cloud Platform for a 12-month period.

---

## Budget Summary

| Category | Annual Budget (USD) |
|---|---|
| GCP Infrastructure | $2,400 |
| AI Model Usage (Gemini) | $1,200 |
| Third-Party API Costs | $0 |
| Development & Tooling | $1,800 |
| **Total** | **$5,400** |

---

## 1. GCP Infrastructure Budget

| Resource | Unit Cost | Estimated Usage | Monthly | Annual |
|---|---|---|---|---|
| Vertex AI Agent Engine | $0.05/hr (managed runtime) | 730 hr/month | $36.50 | $438 |
| Cloud Run Job (scheduler) | $0.000024/vCPU-sec | 2 runs/day × 30s × 1 vCPU | $0.07 | $0.86 |
| Firestore (usage DB) | $0.06/100K reads, $0.18/100K writes | 50K reads + 5K writes/month | $0.04 | $0.48 |
| Cloud Storage (GCS) | $0.020/GB/month | 1 GB (config + prompts) | $0.02 | $0.24 |
| Cloud Monitoring | Included | (reads only — no custom metrics) | $0 | $0 |
| Cloud Quotas API | Included | (read-only) | $0 | $0 |
| Cloud Scheduler | $0.10/job/month | 3 jobs | $0.30 | $3.60 |
| Artifact Registry | $0.10/GB/month | 2 GB (scheduler image) | $0.20 | $2.40 |
| **GCP Infrastructure Subtotal** | | | **$37.13** | **$445.58** |

> Note: Costs above reflect a small-to-medium deployment (10–50 active users querying ops data). Monitoring API calls are billed as part of existing Cloud Monitoring quota.

---

## 2. AI Model Usage Budget (Gemini)

Gemini 2.5 Flash is used for agent responses. OpsIQ queries are typically short (metric lookups), so token usage is low compared to Knowledge IQ.

| Usage Type | Model | Input Price | Output Price | Est. Monthly Tokens | Monthly Cost |
|---|---|---|---|---|---|
| Agent queries (ops questions) | Gemini 2.5 Flash | $0.15/1M | $0.60/1M | 2M in / 0.5M out | $0.60 |
| Scheduled report generation | Gemini 2.5 Flash | $0.15/1M | $0.60/1M | 0.2M in / 0.1M out | $0.09 |
| **Monthly subtotal** | | | | | **$0.69** |
| **Annual subtotal** | | | | | **$8.28** |

> Budget allocation: $1,200/year provides headroom for 10–20× usage growth (e.g. more users, more scheduled reports) without budget revision.

---

## 3. Third-Party API Costs

OpsIQ exclusively uses GCP-native APIs (Cloud Monitoring, Cloud Quotas, Vertex AI Admin, Firestore). All are included in the GCP project billing — no third-party API subscriptions required.

| Service | Cost |
|---|---|
| Cloud Monitoring (reads) | $0 (included in GCP) |
| Cloud Quotas API | $0 (included in GCP) |
| Vertex AI Admin API | $0 (included in GCP) |
| Firestore | See GCP Infrastructure |
| Email dispatch (Email MCP) | Shared with other agents |
| **Third-Party Subtotal** | **$0** |

---

## 4. Development & Tooling Budget

| Item | Cost |
|---|---|
| Developer time (initial build) — 1 week × 1 engineer | Capitalised |
| GCP Sandbox / Dev environment | $50/month × 12 = $600 |
| Monitoring & alerting (Cloud Monitoring dashboards) | $25/month × 12 = $300 |
| Logging (Cloud Logging) | $25/month × 12 = $300 |
| Documentation & testing | $50/month × 12 = $600 |
| **Tooling Subtotal** | **$1,800** |

---

## 5. Budget Allocation by Phase

| Phase | Timeline | Budget |
|---|---|---|
| Phase 1 — Infrastructure setup & core agent | Week 1 | $300 |
| Phase 2 — Tool integrations & scheduler | Week 2–3 | $500 |
| Phase 3 — Production deployment & hardening | Week 4 | $400 |
| Phase 4 — Steady-state operations | Month 2–12 | $4,200 |
| **Total** | **12 months** | **$5,400** |

---

## 6. Budget Assumptions

1. **User base**: 5–20 concurrent users querying ops metrics.
2. **Query volume**: ~50 ops queries/day average.
3. **Scheduler**: 2 jobs (hourly alert check + daily EOD summary).
4. **No GPU usage**: Gemini models are fully managed; no GPU VM costs.
5. **Region**: `us-central1` pricing used throughout.
6. **Firestore**: Write path triggered by `after_model_callback` on each agent response.

---

## 7. Budget Approval

| Role | Name | Approved |
|---|---|---|
| Product Owner | — | Pending |
| Engineering Lead | — | Pending |
| Finance | — | Pending |

*Budget revision required if query volume exceeds 500/day or if additional scheduled reports are added.*
