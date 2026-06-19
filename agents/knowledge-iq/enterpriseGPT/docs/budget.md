# enterpriseGPT — Project Budget

## Overview

This document outlines the approved budget for building, deploying, and operating the enterpriseGPT (Knowledge IQ) agent on Google Cloud Platform for a 12-month period.

---

## Budget Summary

| Category | Annual Budget (USD) |
|---|---|
| GCP Infrastructure | $8,400 |
| AI Model Usage (Gemini) | $6,000 |
| Third-Party API Costs | $1,200 |
| Development & Tooling | $2,400 |
| **Total** | **$18,000** |

---

## 1. GCP Infrastructure Budget

| Resource | Unit Cost | Estimated Usage | Monthly | Annual |
|---|---|---|---|---|
| Vertex AI Agent Engine | $0.05/hr (managed runtime) | 730 hr/month | $36.50 | $438 |
| Vertex AI RAG — Storage | $0.01/GB/month | 50 GB | $0.50 | $6 |
| Vertex AI RAG — Retrieval | $0.000040/query | 10,000 queries/month | $0.40 | $4.80 |
| Cloud Run — Sync Job | $0.000024/vCPU-sec | 2 hr/day × 1 vCPU | $1.44 | $17.28 |
| Cloud Run — Webhook Service | $0.000024/vCPU-sec | always-on min instance | $5.00 | $60 |
| Cloud Storage (GCS) | $0.020/GB/month | 10 GB | $0.20 | $2.40 |
| Artifact Registry | $0.10/GB/month | 5 GB images | $0.50 | $6 |
| Cloud Scheduler | $0.10/job/month | 2 jobs | $0.20 | $2.40 |
| Secret Manager | $0.06/10K ops | 50K ops/month | $0.30 | $3.60 |
| **GCP Infrastructure Subtotal** | | | **$44.54** | **$540** |

> Note: Costs above reflect a small-to-medium deployment (10–50 active users). See Cost Report for scaling projections.

---

## 2. AI Model Usage Budget (Gemini)

Gemini 2.5 Flash is used for both the agent (query responses) and the sync service (keyword extraction during document ingestion).

| Usage Type | Model | Input Price | Output Price | Est. Monthly Tokens | Monthly Cost |
|---|---|---|---|---|---|
| Agent queries | Gemini 2.5 Flash | $0.15/1M | $0.60/1M | 5M in / 1M out | $1.35 |
| Sync keyword extraction | Gemini 2.5 Flash | $0.15/1M | $0.60/1M | 0.5M in / 0.1M out | $0.135 |
| **Monthly subtotal** | | | | | **$1.49** |
| **Annual subtotal** | | | | | **$17.88** |

> Budget allocation: $6,000/year provides headroom for 3–5× usage growth without budget revision.

---

## 3. Third-Party API Costs Budget

| Service | Purpose | Pricing Model | Est. Annual Cost |
|---|---|---|---|
| GitHub API | Code search, repo intelligence | Free (PAT, rate-limited) | $0 |
| Atlassian Jira/Confluence | Issue + wiki search | Included in existing licence | $0 |
| Microsoft Graph (SharePoint) | Document access, delta sync | Included in M365 licence | $0 |
| Gmail API | Email search | Included in Google Workspace | $0 |
| HubSpot API (CRM agent) | CRM operations | Included in HubSpot licence | $0 |
| Apollo / Clearbit (enrichment) | Company firmographics | $99/month | $1,188 |
| **Third-Party Subtotal** | | | **$1,188** |

---

## 4. Development & Tooling Budget

| Item | Cost |
|---|---|
| Developer time (initial build) — 4 weeks × 1 engineer | Capitalised |
| GCP Sandbox / Dev environment | $100/month × 12 = $1,200 |
| Monitoring & alerting (Cloud Monitoring) | $50/month × 12 = $600 |
| Logging (Cloud Logging — beyond free tier) | $50/month × 12 = $600 |
| **Tooling Subtotal** | **$2,400** |

---

## 5. Budget Allocation by Phase

| Phase | Timeline | Budget |
|---|---|---|
| Phase 1 — Infrastructure setup & core agent | Month 1 | $800 |
| Phase 2 — Connector integrations & sync service | Month 2–3 | $1,500 |
| Phase 3 — Production deployment & hardening | Month 4 | $1,200 |
| Phase 4 — Steady-state operations | Month 5–12 | $14,500 |
| **Total** | **12 months** | **$18,000** |

---

## 6. Budget Assumptions

1. **User base**: 10–50 concurrent users; each generates ~20 queries/day.
2. **Document corpus**: ~5,000 documents, average 10 KB each = ~50 GB RAG storage.
3. **Sync frequency**: Hourly for SharePoint (delta), event-driven for GitHub (webhooks).
4. **Retention**: Logs retained for 30 days; GCS state retained indefinitely.
5. **No GPU usage**: Gemini models are fully managed; no GPU VM costs.
6. **Region**: `us-central1` pricing used throughout.

---

## 7. Budget Approval

| Role | Name | Approved |
|---|---|---|
| Product Owner | — | Pending |
| Engineering Lead | — | Pending |
| Finance | — | Pending |

*Budget revision required if user base exceeds 100 active users or corpus exceeds 200 GB.*
