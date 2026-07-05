# Connector Credentials Setup Guide

This guide walks end-users and clients through generating the credentials required for each EnterpriseGPT connector. Follow the steps for each connector you wish to enable.

---

## Table of Contents

1. [Gmail & Google Drive (Google Workspace)](#1-gmail--google-drive-google-workspace)
2. [Google Calendar](#2-google-calendar)
3. [GitHub](#3-github)
4. [Jira & Confluence (Atlassian)](#4-jira--confluence-atlassian)
5. [SharePoint, OneDrive & Outlook (Microsoft 365)](#5-sharepoint-onedrive--outlook-microsoft-365)
6. [Notion](#6-notion)
7. [HubSpot](#7-hubspot)
8. [Apollo.io](#8-apolloio)
9. [Credential Delivery Checklist](#9-credential-delivery-checklist)

---

## 1. Gmail & Google Drive (Google Workspace)

Both Gmail and Google Drive share the same Google Service Account key. You only need to create one service account for both.

**What you will provide:**
- A Service Account JSON key file (uploaded to a GCS bucket path we give you)
- The email address of the user whose mailbox/drive will be accessed

### Step 1 — Enable the APIs

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and select or create a project.
2. Navigate to **APIs & Services → Library**.
3. Search for and **Enable** each of the following:
   - `Gmail API`
   - `Google Drive API`
4. Click **Enable** for each.

### Step 2 — Create a Service Account

1. Go to **IAM & Admin → Service Accounts**.
2. Click **+ Create Service Account**.
3. Fill in:
   - **Name:** `enterprisegpt-connector` (or any recognizable name)
   - **Description:** EnterpriseGPT data connector
4. Click **Create and Continue**, skip optional role assignments, click **Done**.

### Step 3 — Generate the JSON Key

1. Click on the service account you just created.
2. Go to the **Keys** tab → **Add Key → Create new key**.
3. Select **JSON**, click **Create**.
4. A `.json` file downloads automatically — keep it safe, this is your credential file.

### Step 4 — Enable Domain-Wide Delegation

> This step requires **Google Workspace Admin** access.

1. Still on the service account page, click **Advanced settings** (or **Show domain-wide delegation**).
2. Check **Enable Google Workspace Domain-wide Delegation**.
3. Note the **Client ID** shown.

4. Go to [Google Workspace Admin Console](https://admin.google.com/) → **Security → API Controls → Domain-wide Delegation**.
5. Click **Add new** and enter:
   - **Client ID:** (the one from step 3)
   - **OAuth Scopes:**
     ```
     https://www.googleapis.com/auth/gmail.readonly,
     https://www.googleapis.com/auth/drive.readonly
     ```
6. Click **Authorize**.

### What to hand over

| Field | Value |
|---|---|
| `GMAIL_SA_KEY_GCS_URI` | GCS path where you uploaded the JSON key |
| `GMAIL_USER_EMAIL` | e.g. `user@yourcompany.com` |
| `GDRIVE_SA_KEY_GCS_URI` | Same GCS path as above |
| `GDRIVE_USER_EMAIL` | e.g. `user@yourcompany.com` |

---

## 2. Google Calendar

Google Calendar uses the **same service account** created in Section 1. You only need to share the calendar with the service account.

### Step 1 — Share the Calendar

1. Open [Google Calendar](https://calendar.google.com/).
2. On the left panel, hover over the calendar you want to connect, click the three-dot menu → **Settings and sharing**.
3. Under **Share with specific people or groups**, click **+ Add people**.
4. Enter the service account email (e.g. `enterprisegpt-connector@your-project.iam.gserviceaccount.com`).
5. Set permission to **See all event details**, click **Send**.

### Step 2 — Enable the Calendar API

1. In Google Cloud Console, go to **APIs & Services → Library**.
2. Search for `Google Calendar API` and **Enable** it.

### What to hand over

| Field | Value |
|---|---|
| `CALENDAR_SA_KEY_GCS_URI` | Same GCS path as Gmail/Drive JSON key |
| `GOOGLE_CALENDAR_ID` | e.g. `user@yourcompany.com` or a calendar ID |
| `CALENDAR_USER_EMAIL` | e.g. `user@yourcompany.com` |
| `CALENDAR_TIMEZONE` | e.g. `Asia/Kolkata`, `America/New_York` |

---

## 3. GitHub

**What you will provide:** A Personal Access Token (classic or fine-grained).

### Step 1 — Create a Personal Access Token (Classic)

1. Go to [GitHub.com](https://github.com) → Click your avatar (top-right) → **Settings**.
2. In the left sidebar, scroll down to **Developer settings → Personal access tokens → Tokens (classic)**.
3. Click **Generate new token (classic)**.
4. Fill in:
   - **Note:** `EnterpriseGPT Connector`
   - **Expiration:** Choose an expiry (90 days recommended; set a reminder to rotate)
5. Select the following scopes:
   - `repo` (full repository access — read code, issues, PRs)
   - `read:org` (read organisation membership)
   - `read:user`
6. Click **Generate token** and copy it immediately (it is shown only once).

### Alternative — Fine-Grained Token (recommended for stricter access)

1. Go to **Developer settings → Personal access tokens → Fine-grained tokens**.
2. Click **Generate new token**.
3. Set repository access to the specific repos you want to expose.
4. Under **Permissions**, enable **Read** for:
   - `Contents`, `Issues`, `Pull requests`, `Metadata`
5. Generate and copy the token.

### What to hand over

| Field | Value |
|---|---|
| `GITHUB_TOKEN` | `ghp_xxxxxxxxxxxx` |
| `GITHUB_DEFAULT_ORG` | e.g. `your-github-org-name` |

---

## 4. Jira & Confluence (Atlassian)

Both Jira and Confluence use an **Atlassian API Token** tied to your Atlassian account email.

**What you will provide:** Your Atlassian site URL, account email, and an API token.

### Step 1 — Generate an API Token

1. Go to [Atlassian API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens).
2. Click **Create API token**.
3. Enter a label: `EnterpriseGPT Connector`.
4. Click **Create**, then **Copy** the token immediately.

### Step 2 — Find your Atlassian Site URL

Your site URL looks like: `https://your-org.atlassian.net`

You can find it by logging into Jira or Confluence and copying the base URL from the browser address bar.

### What to hand over (Jira)

| Field | Value |
|---|---|
| `JIRA_URL` | `https://your-org.atlassian.net` |
| `JIRA_USERNAME` | `user@yourcompany.com` |
| `JIRA_API_TOKEN` | The token you copied above |

### What to hand over (Confluence)

| Field | Value |
|---|---|
| `CONFLUENCE_URL` | `https://your-org.atlassian.net/wiki` |
| `CONFLUENCE_USERNAME` | `user@yourcompany.com` |
| `CONFLUENCE_API_TOKEN` | Same token as Jira above |

> **Note:** The same API token works for both Jira and Confluence within the same Atlassian account.

---

## 5. SharePoint, OneDrive & Outlook (Microsoft 365)

All three Microsoft connectors use an **Azure Active Directory (Azure AD) App Registration**. One app registration covers all three.

**What you will provide:** Tenant ID, Client ID, and Client Secret.

### Step 1 — Register an App in Azure AD

1. Go to [Azure Portal](https://portal.azure.com/) → **Azure Active Directory** (or search "Microsoft Entra ID").
2. Click **App registrations → + New registration**.
3. Fill in:
   - **Name:** `EnterpriseGPT Connector`
   - **Supported account types:** Accounts in this organizational directory only (single tenant)
4. Click **Register**.
5. Copy the **Application (client) ID** and **Directory (tenant) ID** from the overview page.

### Step 2 — Add API Permissions

1. In the app, go to **API permissions → + Add a permission**.
2. Select **Microsoft Graph → Application permissions** and add:

   | Permission | Purpose |
   |---|---|
   | `Sites.Read.All` | SharePoint site content |
   | `Files.Read.All` | OneDrive files |
   | `Mail.Read` | Outlook email |
   | `Calendars.Read` | Outlook calendar (optional) |
   | `User.Read.All` | Resolve user information |

3. Click **Add permissions**.
4. Click **Grant admin consent for [your org]** and confirm.

### Step 3 — Create a Client Secret

1. Go to **Certificates & secrets → + New client secret**.
2. Enter a description: `EnterpriseGPT`, set an expiry (12 or 24 months).
3. Click **Add**, then copy the **Value** immediately (shown only once).

### What to hand over (SharePoint)

| Field | Value |
|---|---|
| `SHAREPOINT_TENANT_ID` | Directory (tenant) ID |
| `SHAREPOINT_CLIENT_ID` | Application (client) ID |
| `SHAREPOINT_CLIENT_SECRET` | Client secret value |
| `SHAREPOINT_SITE_URL` | e.g. `https://yourorg.sharepoint.com/sites/YourSite` |

### What to hand over (OneDrive)

| Field | Value |
|---|---|
| `ONEDRIVE_TENANT_ID` | Directory (tenant) ID |
| `ONEDRIVE_CLIENT_ID` | Application (client) ID |
| `ONEDRIVE_CLIENT_SECRET` | Client secret value |
| `ONEDRIVE_USER_EMAIL` | e.g. `user@yourcompany.com` |

### What to hand over (Outlook)

| Field | Value |
|---|---|
| `OUTLOOK_TENANT_ID` | Directory (tenant) ID |
| `OUTLOOK_CLIENT_ID` | Application (client) ID |
| `OUTLOOK_CLIENT_SECRET` | Client secret value |
| `OUTLOOK_USER_EMAIL` | e.g. `user@yourcompany.com` |

---

## 6. Notion

**What you will provide:** A Notion Internal Integration Token.

### Step 1 — Create an Integration

1. Go to [Notion Integrations](https://www.notion.so/my-integrations).
2. Click **+ New integration**.
3. Fill in:
   - **Name:** `EnterpriseGPT`
   - **Associated workspace:** Select your workspace
   - **Capabilities:** Enable **Read content**
4. Click **Submit**.
5. Copy the **Internal Integration Token** (starts with `secret_`).

### Step 2 — Share Pages with the Integration

For every Notion page or database you want the connector to access:

1. Open the page in Notion.
2. Click **Share** (top-right) → **Invite**.
3. Search for `EnterpriseGPT` (your integration name) and select it.
4. Click **Invite**.

### What to hand over

| Field | Value |
|---|---|
| `NOTION_API_TOKEN` | `secret_xxxxxxxxxxxx` |

---

## 7. HubSpot

**What you will provide:** A HubSpot Private App access token.

### Step 1 — Create a Private App

1. Log in to [HubSpot](https://app.hubspot.com/).
2. Click the **Settings** gear (top-right) → **Integrations → Private Apps**.
3. Click **Create a private app**.
4. Fill in:
   - **Name:** `EnterpriseGPT Connector`
   - **Description:** EnterpriseGPT data connector
5. Go to the **Scopes** tab and enable (under CRM):
   - `crm.objects.contacts.read`
   - `crm.objects.companies.read`
   - `crm.objects.deals.read`
   - `crm.objects.line_items.read`
   - `tickets` (if you use the Service Hub)
6. Click **Create app**, then **Continue creating**.
7. Copy the **Access token** shown on the confirmation screen.

### What to hand over

| Field | Value |
|---|---|
| `HUBSPOT_API_TOKEN` | `pat-na1-xxxxxxxxxxxx` |
| `HUBSPOT_PORTAL_ID` | Your HubSpot Account/Portal ID (found in Settings → Account Setup → Account ID) |

---

## 8. Apollo.io

**What you will provide:** An Apollo.io API Key.

### Step 1 — Generate an API Key

1. Log in to [Apollo.io](https://app.apollo.io/).
2. Click your avatar (top-right) → **Settings**.
3. Go to **Integrations → API** (or navigate directly to `https://app.apollo.io/#/settings/integrations/api`).
4. Click **+ Create API Key**.
5. Enter a name: `EnterpriseGPT Connector`.
6. Click **Create** and copy the key immediately.

### What to hand over

| Field | Value |
|---|---|
| `APOLLO_API_KEY` | Your Apollo.io API key |

---

## 9. Credential Delivery Checklist

Once you have generated all required credentials, send them securely to the Stratova team using one of the following methods:

- **Preferred:** Upload credential files (e.g. Google Service Account JSON) directly to the designated GCS bucket path provided by Stratova.
- **For tokens/secrets:** Share via a secure secrets tool (1Password, Bitwarden Send, or a password-manager share link) — never send via plain email or chat.

### Summary table

| Connector | Credential Type | Env Variables |
|---|---|---|
| Gmail | Google Service Account JSON | `GMAIL_SA_KEY_GCS_URI`, `GMAIL_USER_EMAIL` |
| Google Drive | Google Service Account JSON | `GDRIVE_SA_KEY_GCS_URI`, `GDRIVE_USER_EMAIL` |
| Google Calendar | Google Service Account JSON | `CALENDAR_SA_KEY_GCS_URI`, `GOOGLE_CALENDAR_ID` |
| GitHub | Personal Access Token | `GITHUB_TOKEN`, `GITHUB_DEFAULT_ORG` |
| Jira | Atlassian API Token | `JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN` |
| Confluence | Atlassian API Token | `CONFLUENCE_URL`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN` |
| SharePoint | Azure AD App | `SHAREPOINT_TENANT_ID`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET` |
| OneDrive | Azure AD App | `ONEDRIVE_TENANT_ID`, `ONEDRIVE_CLIENT_ID`, `ONEDRIVE_CLIENT_SECRET` |
| Outlook | Azure AD App | `OUTLOOK_TENANT_ID`, `OUTLOOK_CLIENT_ID`, `OUTLOOK_CLIENT_SECRET` |
| Notion | Integration Token | `NOTION_API_TOKEN` |
| HubSpot | Private App Token | `HUBSPOT_API_TOKEN`, `HUBSPOT_PORTAL_ID` |
| Apollo.io | API Key | `APOLLO_API_KEY` |

> **Security reminder:** Treat all tokens and keys like passwords. Rotate them on a schedule (every 90 days recommended) and revoke any key immediately if it is accidentally exposed.
