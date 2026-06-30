# Knowledge-IQ — Sample Prompts Reference

A curated list of working prompts for every agent in the Knowledge-IQ system.
Prompts are derived directly from each agent's `tools_config.json` and tool
implementations. Tools marked **DISABLED** in the active config are excluded.

---

## Live tool status (from `enterpriseGPT/config/tools_config.json`)

| Tool | Status |
|---|---|
| RAG Knowledge Base | **ENABLED** |
| Gmail | **ENABLED** |
| Google Drive | **ENABLED** |
| Google Chat | **ENABLED** |
| GitHub | **ENABLED** |
| Jira | **ENABLED** |
| Confluence | **ENABLED** |
| SharePoint | **ENABLED** |
| OneDrive | **ENABLED** |
| Outlook | **ENABLED** |
| Notion | **ENABLED** |
| Gemini Connectors | DISABLED |
| Zoho CRM / Desk / Books / People | DISABLED |

---

## 1. Orchestrator Agent

The orchestrator **routes** — it never answers directly. Send it any upload or search
request and it will delegate to the correct sub-agent.

### 1.1 Document upload / ingest routing

```
Upload this document to the knowledge base:
[paste document text or share a Drive/GCS link]
```

```
Index this file for the whole organisation: gs://stratova-platform/docs/product-brief.pdf
```

```
Save this to the RAG corpus and tag it for the Engineering team.
[paste content]
```

```
Ingest the following meeting notes into the company knowledge base:
[paste notes]
```

```
Add this to the knowledge base — it came from the CRM agent:
[paste CRM export text]
source_agent: crm_agent
```

### 1.2 Knowledge search / retrieval routing

```
Find our onboarding policy for new engineers.
```

```
What is our refund policy?
```

```
Search for everything we know about the Acme Corp deal.
```

```
Summarise the latest updates on Project Phoenix.
```

```
Look up the leave policy document.
```

### 1.3 Ambiguous requests (orchestrator will ask one clarifying question)

```
I have a document about Q4 targets — what should I do with it?
```

```
Project Apollo
```

---

## 2. Document Mining Agent

Handles document ingestion into the org-level knowledge base.
**Always analyzes the document before uploading.** Scope choices: `organization`,
`department`, `personal`.

### 2.1 Upload inline text — organization scope

```
Upload this document to the knowledge base:

Title: Remote Work Policy v2
[paste full document text]
```

The agent will:
1. Call `analyze_document_content` and show you the analysis
2. Ask: "Should this be accessible to the whole organisation, or only specific departments?"
3. Upload once you confirm

### 2.2 Upload from Google Drive URL

```
Upload this Google Drive document to the knowledge base:
https://drive.google.com/file/d/1aBcDeFgHiJkLmNo/view

Name it "Product Roadmap Q3 2025".
```

```
Index this Drive file for the Engineering department:
https://drive.google.com/file/d/1XYZ.../view
```

### 2.3 Upload from GCS URI

```
Upload the following GCS file to the knowledge base:
gs://stratova-platform/contracts/vendor-agreement-2025.pdf

Scope: organization
```

```
Ingest gs://stratova-platform/hr/leave-policy.pdf and restrict it to the HR department.
```

### 2.4 Upload with department scope

```
Upload the following document. It should only be visible to the Sales and Marketing teams.

Title: Q2 Pricing Guide
[paste content]
```

```
Save this SOW for the Legal and Finance departments only:
[paste Statement of Work text]
```

Available departments: `sales`, `engineering`, `hr`, `finance`, `legal`, `marketing`,
`operations`, `executive`, `product`, `support`

### 2.5 Upload for personal scope (from Personal Assistant — non-interactive)

The document mining agent processes this automatically when called from the Personal
Assistant. The Personal Assistant sends a structured request like:

```
Upload the following document to the knowledge base.
accessibility_scope: personal
owner_user_id: alice@stratova.ai
display_name: Meeting notes - June standup.txt

Document content:
[full text]
```

No confirmation dialog — the agent uploads immediately and returns the `rag_file_name`.

### 2.6 List documents in the knowledge base

```
List all documents currently in the knowledge base.
```

```
Show me all documents tagged for the Engineering department.
```

```
List all documents uploaded by the crm_agent.
```

```
Show department-scoped documents in the knowledge base.
```

---

## 3. EnterpriseGPT (Knowledge Search Agent)

Searches across all enabled data sources and synthesises answers with citations.
**Never asks which source to search** — it queries all relevant sources autonomously.

### 3.1 RAG Knowledge Base (internal document corpus)

```
What is our company's parental leave policy?
```

```
Summarise the product requirements document for the mobile app.
```

```
Find any document about the vendor SLA for CloudProvider X.
```

```
What onboarding steps are required for a new Sales hire?
```

```
Search the knowledge base for anything related to GDPR compliance.
```

```
What have we documented about our API rate limits?
```

### 3.2 Gmail

```
Find emails from sarah@acme.com received this month.
```

```
Search my Gmail for the invoice from TechVendor Ltd sent last week.
```

```
Show me any emails with the subject line "Q3 Budget Approval".
```

```
Find any email thread about the office lease renewal.
```

```
Did I receive any emails from the HR team about the performance review cycle?
```

### 3.3 Google Drive

```
Find the product roadmap deck on Drive.
```

```
Search Drive for the Q4 OKR spreadsheet.
```

```
Is there a presentation about the fundraising round on Google Drive?
```

```
Find the design specifications document for the checkout flow on Drive.
```

### 3.4 Google Chat

```
What was discussed in the #engineering channel about the deployment issue last week?
```

```
Search Google Chat for any messages about the Acme Corp integration.
```

```
Find any Chat messages from Abdul about the API migration.
```

### 3.5 GitHub

```
Find open pull requests in the stratova-ai/Stratova repo.
```

```
Search GitHub for issues tagged 'bug' in the main repo.
```

```
Show me recent commits to the main branch of stratova-ai/Stratova.
```

```
Are there any GitHub issues about authentication failures?
```

```
Find the README for the laabu-ai-app repository.
```

```
What issues are currently open in the stratova-ai org?
```

### 3.6 Jira

```
What Jira tickets are currently in progress for the Engineering team?
```

```
Find the Jira ticket about the payment gateway bug.
```

```
List all open Jira issues assigned to me.
```

```
What is the status of ticket ENG-142?
```

```
Show all Jira bugs with priority Critical.
```

```
Search Jira for any tickets related to the mobile release.
```

### 3.7 Confluence

```
What does our Confluence wiki say about the deployment process?
```

```
Find the engineering runbook on Confluence.
```

```
Search Confluence for documentation on database migrations.
```

```
Is there a Confluence page about our incident response procedure?
```

```
Find the product specs page for the notification system on Confluence.
```

### 3.8 SharePoint

```
Find the HR handbook on SharePoint.
```

```
Search SharePoint for the latest finance report.
```

```
Is the company org chart stored on SharePoint?
```

```
Find the procurement policy document on SharePoint.
```

### 3.9 OneDrive

```
Find the Q1 budget spreadsheet on OneDrive.
```

```
Search OneDrive for the contract template.
```

```
Is there a marketing calendar on OneDrive?
```

### 3.10 Outlook

```
Find the email thread about the AWS cost review from last month.
```

```
Search Outlook for any messages from procurement@stratova.ai.
```

```
Did someone send a meeting invite for the all-hands next week via Outlook?
```

```
Find any Outlook emails with attachments from the Legal team this quarter.
```

### 3.11 Notion

```
What does our Notion workspace say about the product vision?
```

```
Search Notion for the content calendar.
```

```
Find the Notion page about our hiring process.
```

```
Is there a Notion database tracking customer feedback?
```

### 3.12 Multi-source / cross-source questions

The agent searches all relevant sources and merges the answer:

```
What do we know about Project Atlas? Check all connected sources.
```

```
Find everything about the vendor NDA for DataCo — check Drive, SharePoint, and the knowledge base.
```

```
Summarise all information we have on the AWS cost optimisation initiative.
```

```
What is the current status of the mobile app launch? Check Jira, Confluence, and Gmail.
```

### 3.13 Date-relative queries

The agent uses the injected current date — never calls a tool for today's date:

```
What happened in the engineering standup yesterday?
```

```
Show me any Jira tickets created this week.
```

```
Find Gmail threads from last month about the annual audit.
```

```
What GitHub PRs were merged in the last 7 days?
```

### 3.14 Personal knowledge base — upload a file attachment

Click the 📎 (paperclip / "+" button) in Agentspace to attach a file, then send:

```
Upload this file to my personal knowledge base.
```

```
Save this PDF to my documents.
```

```
Index this attached contract for my personal use.
```

Supported file types: PDF, DOCX, PPTX, TXT, MD, HTML, JSON, PY, SQL

### 3.15 Personal knowledge base — upload via Drive URL or GCS URI

```
Upload this Drive file to my personal knowledge base:
https://drive.google.com/file/d/1aBcXYZ/view
```

```
Add this GCS file to my documents:
gs://stratova-platform/my-notes/architecture-draft.md
```

### 3.16 Personal knowledge base — search and manage

```
Search my documents for anything about the Q3 client proposal.
```

```
What files have I uploaded to my personal knowledge base?
```

```
List my documents.
```

```
Delete my document named "old-notes.txt" from my knowledge base.
```

### 3.17 Sub-agent delegation (CRM, Enrichment, Web Scraper)

These are routed transparently — just ask naturally:

```
Find the HubSpot deal record for Acme Corp.
```

```
What is the current stage of our deal with TechStartup Inc in the CRM?
```

```
Enrich the company profile for DataCo Ltd.
```

```
Scrape this URL and summarise the content:
https://techstartup.io/about
```

```
Add a note to the HubSpot contact for john.doe@client.com.
```

---

## 4. Personal Assistant Agent

A private copilot grounded in the user's own documents. Each user sees only their
own files. Also handles general knowledge, drafting, and everyday tasks.

### 4.1 General assistance — no tools required

```
Draft a professional email declining a vendor meeting politely.
```

```
Summarise the following meeting transcript in 5 bullet points:
[paste transcript]
```

```
Explain what a RAG pipeline is in simple terms.
```

```
Help me write a performance self-review for Q2.
```

```
Create a weekly status update template I can fill in each Friday.
```

```
Translate the following paragraph to French:
[paste text]
```

```
What are some best practices for writing a technical specification document?
```

### 4.2 Search personal documents

```
Search my documents for anything about the client onboarding checklist.
```

```
Find my notes on the AWS architecture review.
```

```
Do I have anything saved about the Acme Corp contract?
```

```
Search my knowledge base for Python async patterns.
```

```
Find my personal notes from the engineering retrospective last sprint.
```

### 4.3 Upload a document to personal knowledge base

The agent extracts the text and routes it to the document mining agent as personal scope:

```
Save this for me — it's my personal meeting notes:
[paste content]
```

```
Upload the following to my personal knowledge base. Call it "API Design Notes June 2025":
[paste content]
```

```
Store this document privately — only I should be able to search it:
[paste text]
```

### 4.4 List personal documents

```
What documents have I uploaded?
```

```
Show me my personal knowledge base files.
```

```
List all my uploaded documents.
```

### 4.5 Search then draft (combined flow)

```
Search my documents for the client brief, then draft a project proposal outline based on it.
```

```
Find my notes on the Q3 budget and write a summary email to the finance team.
```

```
Look up my personal notes on the authentication redesign and draft a Jira ticket description.
```

---

## Notes on scope and access control

| Scope | Who can search it |
|---|---|
| `organization` | Everyone in the org (via EnterpriseGPT) |
| `department` | Only members of the specified departments |
| `personal` | Only the user who uploaded it (via Personal Assistant) |

Admin users (`abdul@stratova.ai`, `ms@stratova.ai`, `darrell@stratova.ai`,
`keerthana@stratova.ai`, `meera@stratova.ai`) can search all documents regardless
of scope when `admin_access_control_enabled` is `true`.
