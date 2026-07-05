# OpsIQ — Cost Report

**Period:** June 2026 (Month 1 — Initial Deployment)
**Project:** `ninth-archway-496404-s2`
**Region:** `us-central1`

---

## Executive Summary

| Item | Budget (Month 1) | Actual / Estimated | Variance |
|---|---|---|---|
| GCP Infrastructure | $300 | $38.20 | -$261.80 (under) |
| AI Model Usage | $100 | $0.69 | -$99.31 (under) |
| Third-Party APIs | $0 | $0 | $0 |
| Dev / Tooling | $400 | $150 | -$250 (under) |
| **Total** | **$800** | **$188.89** | **-$611.11** |

> Month 1 is significantly under budget — expected. The agent is in initial deployment/testing with low traffic volume. Full steady-state costs will be visible from Month 3.

---

## 1. GCP Infrastructure Costs (Month 1)

### Vertex AI Agent Engine
| Resource | Usage | Unit Cost | Cost |
|---|---|---|---|
| Agent Engine managed runtime | 730 hours | $0.05/hr | $36.50 |
| Agent Engine API calls | ~200 calls (testing) | Included in runtime | $0.00 |
| **Subtotal** | | | **$36.50** |

### Cloud Run Job (Scheduler)
| Resource | Usage | Unit Cost | Cost |
|---|---|---|---|
| Hourly alert check (48 runs × 30s × 1 vCPU) | 1,440 vCPU-sec | $0.000024/vCPU-sec | $0.035 |
| Daily EOD summary (30 runs × 60s × 1 vCPU) | 1,800 vCPU-sec | $0.000024/vCPU-sec | $0.043 |
| **Subtotal** | | | **$0.078** |

### Firestore
| Resource | Usage | Unit Cost | Cost |
|---|---|---|---|
| Document writes (usage events) | ~5,000 writes | $0.18/100K | $0.009 |
| Document reads (query responses) | ~20,000 reads | $0.06/100K | $0.012 |
| **Subtotal** | | | **$0.021** |

### Storage & Other
| Resource | Usage | Unit Cost | Cost |
|---|---|---|---|
| Cloud Storage (config + prompts) | 0.2 GB | $0.020/GB/month | $0.004 |
| Cloud Scheduler | 3 jobs | $0.10/job/month | $0.30 |
| Artifact Registry | 1.5 GB (scheduler image) | $0.10/GB/month | $0.15 |
| **Subtotal** | | | **$0.454** |

### GCP Infrastructure Total: **$37.05**

---

## 2. AI Model Usage Costs (Month 1)

Gemini 2.5 Flash pricing: **$0.15 / 1M input tokens**, **$0.60 / 1M output tokens**

| Usage Type | Input Tokens | Output Tokens | Input Cost | Output Cost | Total |
|---|---|---|---|---|---|
| Agent ops queries (~200 queries, avg 5K in / 1K out) | 1,000,000 | 200,000 | $0.150 | $0.120 | $0.270 |
| Scheduled reports (~60 runs, avg 3K in / 2K out) | 180,000 | 120,000 | $0.027 | $0.072 | $0.099 |
| Testing / development | 500,000 | 100,000 | $0.075 | $0.060 | $0.135 |
| **Monthly Total** | | | | | **$0.504** |

> Well under the $100 budget — Ops IQ queries are short-form (metric lookups), not long-context document retrieval like Knowledge IQ.

---

## 3. Third-Party API Costs (Month 1)

OpsIQ uses only GCP-native APIs — all included in GCP billing.

| Service | Cost |
|---|---|
| Cloud Monitoring reads | $0 |
| Cloud Quotas API reads | $0 |
| Vertex AI Admin API reads | $0 |
| **Total** | **$0** |

---

## 4. Month-over-Month Projections

Assuming 5× traffic growth by Month 6 (steady state):

| Month | Est. Agent Engine | Est. Gemini | Est. Other GCP | **Total** |
|---|---|---|---|---|
| 1 (now) | $36.50 | $0.50 | $1.07 | **$38.07** |
| 2 | $36.50 | $1.00 | $1.50 | **$39.00** |
| 3 | $36.50 | $2.50 | $2.00 | **$41.00** |
| 6 | $36.50 | $5.00 | $3.00 | **$44.50** |
| 12 | $36.50 | $8.00 | $4.00 | **$48.50** |

> OpsIQ costs are dominated by the Agent Engine runtime ($36.50/month flat), which is constant regardless of query volume. Gemini usage scales with traffic but remains negligible given the short query nature.

---

## 5. Cost Optimisation Notes

1. **Agent Engine runtime** is the largest cost and is fixed (always-on managed runtime). Consider pausing in non-production environments.
2. **Gemini token usage** is very low for ops queries — no optimisation needed at current scale.
3. **Firestore** costs are negligible. No action needed.
4. **Scheduler** runs are cheap. Consider increasing frequency without budget impact.

---

## 6. Billing Alerts Configured

| Alert | Threshold | Notification |
|---|---|---|
| Monthly spend > $100 | $100 | Email to `admin@stratova.ai` |
| Monthly spend > $200 | $200 | Email to `admin@stratova.ai` |
| Anomalous spike (> 2× daily average) | Auto | GCP anomaly detection |
