# OpsIQ — Sample Prompts for Testing

Use these prompts to test and validate each monitoring capability. Run them in the ADK web UI at `http://127.0.0.1:8000` or through Gemini AI Enterprise.

---

## 1. Quota Monitoring

### Quota Limits
```
What are our Vertex AI quota limits for aiplatform.googleapis.com?
```
```
List all fixed quotas that cannot be increased for Vertex AI.
```
```
Which quotas are we closest to exhausting?
```

### Quota Headroom
```
Give me a quota headroom summary for Vertex AI.
```
```
Are we close to hitting any Vertex AI rate limits?
```
```
Flag any quotas at over 80% utilisation.
```

### Quota Increase Requests
```
Show me all pending quota increase requests.
```
```
Are any of our quota increase requests in a denied state?
```

---

## 2. LLM Usage Metrics (Cloud Monitoring)

### Token Usage
```
How many tokens did we use in the last 24 hours? Break it down by model.
```
```
Which model is consuming the most tokens this week?
```
```
Show me input vs output token ratio for the last 7 days.
```
```
How many tokens did gemini-2.5-flash consume today?
```

### Request Counts
```
How many API requests did we make to Vertex AI in the last 24 hours?
```
```
Show me request counts by model for the last 7 days.
```
```
What's the peak request hour today?
```

### Latency
```
What is the p95 latency for gemini-2.5-flash in the last 24 hours?
```
```
Show me p50 and p99 latency for all models over the last week.
```
```
Are there any models with latency above 5 seconds?
```

### Error Rates
```
Are there any elevated error rates on Vertex AI models right now?
```
```
Show me error rates by model for the last 24 hours.
```
```
Which model had the highest error rate this week?
```

### Agent Engine Metrics
```
Show me prediction counts for Agent Engines in the last 24 hours.
```
```
What is the request latency for deployed Agent Engines today?
```

---

## 3. Vertex AI Resource Inventory

### Agent Engines
```
List all deployed Vertex AI Agent Engine deployments.
```
```
What is the state of each deployed agent?
```
```
Is the Knowledge IQ agent currently active?
```
```
Which Agent Engines were updated in the last 7 days?
```

### Endpoints & Models
```
Show me all online prediction endpoints in our project.
```
```
What models are deployed to our prediction endpoints?
```
```
List any endpoints in a FAILED state.
```

### Resource Summary
```
Give me a full Vertex AI resource summary — agents, endpoints, and models.
```

---

## 4. Per-User Usage Tracking (Firestore)

### Individual Users
```
How many tokens has abdul@stratova.ai used in the last 7 days?
```
```
Show me the last 20 chat interactions for a specific user.
```
```
What agents has this user interacted with this week?
```

### Leaderboard
```
Who are the top 10 users by token consumption in the last 30 days?
```
```
Which user has made the most requests today?
```

### Per-Agent Breakdown
```
Which agent is used the most across the platform?
```
```
Give me a per-agent token usage breakdown for this week.
```
```
How many requests did the Knowledge IQ agent receive today?
```

---

## 5. Platform Health & Combined Reports

### Health Overview
```
Give me a full platform health report.
```
```
Are there any anomalies or alerts right now?
```
```
How is our Vertex AI platform performing today?
```

### Combined Metrics
```
Show me a combined metrics summary for the platform for the last 24 hours.
```
```
Give me a health summary: quota headroom, token burn, error rates, and resource states.
```

---

## 6. Alerting & Threshold Checks

### Threshold Checks
```
Run a threshold check — are any metrics above their alert thresholds?
```
```
What are the current alert thresholds configured for this platform?
```

### Scheduled Report Preview
```
Generate a status report like the daily scheduled report.
```
```
What would the EOD summary email look like for today?
```

---

## 7. Feature Flag — Disabled Capability

```
Show me Gemini Enterprise usage statistics.
```
→ Expected: agent informs you this capability is currently disabled.

---

## 8. Out-of-Scope Queries

```
Show me all HubSpot contacts created this week.
```
→ Expected: redirected to the appropriate agent (not Ops IQ's domain).

```
Search my emails for the latest invoice.
```
→ Expected: redirected to Knowledge IQ or another appropriate agent.

---

## 9. Agent Self-Awareness

```
What monitoring capabilities do you have?
```
```
Which monitoring modules are currently enabled?
```
```
What can Ops IQ help me with?
```

---

## Quick Smoke Test (run in order)

Run these 5 prompts in sequence to verify all major paths are working:

1. `Give me a quota headroom summary for Vertex AI.`  
   → Tests: quota_tool + config loading

2. `How many tokens did we use in the last 24 hours?`  
   → Tests: metrics_tool + Cloud Monitoring auth

3. `List all deployed Vertex AI Agent Engine deployments.`  
   → Tests: vertex_resources_tool + Vertex AI Admin API auth

4. `Who are the top 10 users by token consumption?`  
   → Tests: usage_tracker_tool + Firestore auth

5. `Show me Gemini Enterprise usage statistics.`  
   → Tests: feature-flag disabled path (no tool call, clean message)
