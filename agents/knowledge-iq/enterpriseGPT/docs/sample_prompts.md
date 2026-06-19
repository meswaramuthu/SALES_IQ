# enterpriseGPT — Sample Prompts for Testing

Use these prompts to test and validate each tool category. Run them in the ADK web UI at `http://127.0.0.1:8082` or through Gemini AI Enterprise.

---

## 1. RAG — Personal Knowledge Base

### Upload & Index
```
Upload this document to my knowledge base: https://example.com/company-policy.pdf
```
```
Save the attached file to my knowledge base so I can search it later.
```
```
Add this GCS file to my knowledge base: gs://my-bucket/docs/onboarding-guide.pdf
```

### Search
```
Search my knowledge base for anything about employee leave policy.
```
```
What do my uploaded documents say about the Q3 OKRs?
```
```
Find documents in my knowledge base related to API authentication.
```

### Manage
```
List all the documents I've uploaded to my knowledge base.
```
```
Delete the document called "old-roadmap.pdf" from my knowledge base.
```

---

## 2. Gemini Enterprise Connector (All Connected Sources)

```
Search across all connected data sources for anything about the product roadmap.
```
```
Find information about our pricing strategy across all my connected documents.
```
```
What do our connected sources say about the onboarding process for new engineers?
```
```
Search everything connected for mentions of "GDPR compliance".
```

---

## 3. GitHub

### Repository Discovery
```
List all repositories in our GitHub organisation.
```
```
Give me details about the stratova-gcp repository — branches, topics, last activity.
```

### Commits & Changes
```
Show me the last 10 commits on the main branch of stratova-gcp.
```
```
What changed in the most recent commit on the feature/laabu-agents-a2a branch?
```
```
Who made changes to agents/knowledge-iq/ in the last 7 days?
```

### Pull Requests
```
List all open pull requests in stratova-gcp.
```
```
What files did PR #42 change? Was it merged?
```
```
Show me all PRs targeting the main branch that are still open.
```

### Issues
```
Search GitHub issues for anything labelled "bug" in the last month.
```
```
Get me the details and comments on issue #15.
```

### Code Search
```
Search the codebase for all usages of "build_rag_tools".
```
```
Show me the content of agents/knowledge-iq/enterpriseGPT/agent.py on main.
```
```
Find all Python files that import from stratova_shared.
```

---

## 4. Jira

```
Search Jira for all open bugs in the KIQDEV project.
```
```
Show me the details of ticket KIQDEV-42.
```
```
List all Jira issues assigned to me that are in progress.
```
```
Find all Jira tickets with priority "High" created in the last 2 weeks.
```
```
What are the open blockers in the current sprint?
```

---

## 5. Confluence

```
Search Confluence for pages about the deployment process.
```
```
Find the Confluence page titled "Architecture Decision Records".
```
```
What does our Confluence say about incident response procedures?
```
```
Get the content of the Engineering onboarding Confluence page.
```

---

## 6. SharePoint

### Sites & Navigation
```
List all SharePoint sites I have access to.
```
```
List the document libraries in the Engineering SharePoint site.
```
```
What files are in the "Contracts" folder of the Legal SharePoint site?
```

### File Search & Content
```
Search SharePoint for any files containing "NDA" in the Legal site.
```
```
Find all PowerPoint presentations modified in the last 30 days.
```
```
Get the content of the file "Q2-2026-Board-Deck.pptx" from SharePoint.
```
```
What are the metadata details (author, size, last modified) of the annual report?
```

### Lists & Pages
```
List all items in the SharePoint "Project Tracker" list where status is "Active".
```
```
Search across all SharePoint content for anything about budget approvals.
```
```
Show me the modern page called "Company News" from the intranet site.
```

---

## 7. Gmail

```
Search my Gmail for emails from legal@company.com in the last 7 days.
```
```
Find all emails with the subject containing "invoice" received this month.
```
```
Show me the full email thread for the message about Q3 planning from Sarah.
```
```
Search Gmail for any emails mentioning "contract renewal" from external senders.
```

---

## 8. A2A — Sub-Agent Routing

### CRM Agent
```
Create a new HubSpot contact for John Smith at Acme Corp — john@acme.com, CEO.
```
```
What deals are currently in the "Proposal Sent" stage in HubSpot?
```
```
Add a note to the HubSpot contact for sarah@techco.com saying we had a discovery call today.
```

### Enrichment Agent
```
Enrich the company for this email: cto@innovatecorp.io — what's their headcount and industry?
```
```
Get firmographic data for the company behind james@globalbank.com.
```

### Web Scraper Agent
```
Scrape the content from https://example.com/about and save it to my knowledge base.
```
```
Fetch and index the content from our competitor's pricing page for research.
```

---

## 9. Cross-Source / Multi-Tool Queries

These prompts test the agent's ability to combine multiple tools in a single response.

```
Find everything we have about Project Phoenix — check Jira, Confluence, SharePoint, and GitHub.
```
```
What is the current status of the API v2 migration? Check GitHub PRs, Jira tickets, and Confluence.
```
```
I need to onboard a new engineer — pull the onboarding guide from my knowledge base and check if there's anything newer in Confluence.
```
```
Search GitHub code and SharePoint for any documentation about our authentication flow.
```
```
What has changed in the codebase this week (GitHub) and are there related Jira tickets open?
```

---

## 10. Agent Self-Awareness

```
What tools do you have available and what is each one used for?
```
```
Which data sources are currently enabled?
```
```
What can you help me with?
```

---

## Quick Smoke Test (run in order)

Run these 5 prompts in sequence to verify all major paths are working:

1. `List all the documents I've uploaded to my knowledge base.`  
   → Tests: RAG tool + config loading

2. `List all repositories in our GitHub organisation.`  
   → Tests: GitHub tool + API auth

3. `Search Jira for all open issues assigned to me.`  
   → Tests: Atlassian tool + API auth

4. `List all SharePoint sites I have access to.`  
   → Tests: Microsoft tool + MSAL auth

5. `What tools do you have available?`  
   → Tests: agent reasoning + prompt injection
