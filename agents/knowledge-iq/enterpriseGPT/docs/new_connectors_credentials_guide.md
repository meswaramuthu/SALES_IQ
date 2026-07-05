# New Connector Credentials Guide — EnterpriseGPT

Step-by-step instructions to obtain API keys, OAuth tokens, and secrets for every new EnterpriseGPT integration. Follow only the sections for connectors you are enabling.

---

## Table of Contents

1. [Overview & Complexity Reference](#overview--complexity-reference)
2. [Zoho OAuth2 Setup (shared by 4 tools)](#zoho-oauth2-setup-shared-by-4-tools)
3. [Google Chat](#1-google-chat)
4. [Slack](#2-slack)
5. [Smartsheet](#3-smartsheet)
6. [Salesforce](#4-salesforce)
7. [Zoho CRM](#5-zoho-crm)
8. [Freshdesk](#6-freshdesk)
9. [Zendesk](#7-zendesk)
10. [Zoho Desk](#8-zoho-desk)
11. [Zoho Books](#9-zoho-books)
12. [Workday](#10-workday)
13. [BambooHR](#11-bamboohr)
14. [Zoho People](#12-zoho-people)
15. [Rippling](#13-rippling)

---

## Overview & Complexity Reference

| Connector     | Config Key     | Auth Type                            | Difficulty |
|---------------|----------------|--------------------------------------|------------|
| Google Chat   | `gchat`        | Service Account JSON / OAuth2        | Medium     |
| Slack         | `slack`        | Bot OAuth Token                      | Easy       |
| Smartsheet    | `smartsheet`   | Personal Access Token                | Easy       |
| Salesforce    | `salesforce`   | Username + Password + Security Token | Medium     |
| Zoho CRM      | `zoho_crm`     | Zoho OAuth2                          | OAuth2     |
| Freshdesk     | `freshdesk`    | API Key                              | Easy       |
| Zendesk       | `zendesk`      | API Token + Email                    | Easy       |
| Zoho Desk     | `zoho_desk`    | Zoho OAuth2 + Org ID                 | OAuth2     |
| Zoho Books    | `zoho_books`   | Zoho OAuth2 + Org ID                 | OAuth2     |
| Workday       | `workday`      | OAuth2 Client Credentials            | Medium     |
| BambooHR      | `bamboohr`     | API Key                              | Easy       |
| Zoho People   | `zoho_people`  | Zoho OAuth2                          | OAuth2     |
| Rippling      | `rippling`     | API Key                              | Easy       |

> **Zoho suite note:** Zoho CRM, Zoho Desk, Zoho Books, and Zoho People all use the same Zoho OAuth2 flow. Complete the [Zoho OAuth2 Setup](#zoho-oauth2-setup-shared-by-4-tools) section once and reuse that token for all four tools.

---

## Zoho OAuth2 Setup (shared by 4 tools)

**Applies to:** Zoho CRM, Zoho Desk, Zoho Books, Zoho People

> ⚠️ Zoho access tokens expire after **1 hour**. For production, implement a token refresh flow using the `refresh_token` you receive in step 4. For testing, regenerate manually from the API Console.

### Step 1 — Go to Zoho API Console

Open [api-console.zoho.com](https://api-console.zoho.com) and sign in with your Zoho administrator account.

### Step 2 — Create a Self-Client Application

1. Click **Add Client** → choose **Self Client**.
2. Name it `EnterpriseGPT Connector`.
3. Click **Create**. Copy the **Client ID** and **Client Secret** that appear.

### Step 3 — Generate a Grant Code with the required scopes

In the Self-Client tab, click **Generate Code**. Enter the scopes you need. Add all scopes for every Zoho product you are enabling:

- **CRM:** `ZohoCRM.modules.ALL,ZohoCRM.settings.modules.READ,ZohoCRM.coql.READ`
- **Desk:** `Desk.tickets.ALL,Desk.contacts.ALL,Desk.search.READ,Desk.basic.READ`
- **Books:** `ZohoBooks.fullaccess.all`
- **People:** `ZOHOPEOPLE.employee.ALL,ZOHOPEOPLE.leave.ALL,ZOHOPEOPLE.org.READ`

Set **Time Duration** to `10 minutes`. Click **Create** — copy the **grant code** immediately.

### Step 4 — Exchange the grant code for access + refresh tokens

Run the following in a terminal (replace the placeholders):

```bash
curl -X POST "https://accounts.zoho.com/oauth/v2/token" \
  -d "code=YOUR_GRANT_CODE" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "grant_type=authorization_code"
```

The response contains `access_token` and `refresh_token`. Save both.

### Step 5 — Determine your data centre base URL

Your Zoho data centre determines which API domain to use:

| Data centre | Base URL                          |
|-------------|-----------------------------------|
| US          | `https://www.zohoapis.com`        |
| EU          | `https://www.zohoapis.eu`         |
| India       | `https://www.zohoapis.in`         |
| Australia   | `https://www.zohoapis.com.au`     |

If unsure, log in to any Zoho product and check the URL in your browser.

> 💡 **Refreshing tokens:** When the access token expires, POST to the same token endpoint with `grant_type=refresh_token&refresh_token=YOUR_REFRESH_TOKEN` to get a new access token without repeating the grant flow.

---

## 1. Google Chat

**Config key:** `gchat`  
**Auth type:** Service Account JSON or short-lived OAuth2 token

### Credentials needed

| Key                | Description |
|--------------------|-------------|
| `credentials_json` | Path to service account JSON file, OR the JSON content itself as a string |
| `access_token`     | Alternative: a short-lived OAuth2 bearer token (if not using a service account) |

### Step 1 — Enable the Google Chat API

1. Go to [Google Cloud Console](https://console.cloud.google.com) → select or create your project.
2. Navigate to **APIs & Services → Library**.
3. Search for **Google Chat API** and click **Enable**.

### Step 2 — Create a Service Account

1. Go to **IAM & Admin → Service Accounts → + Create Service Account**.
2. Name it `enterprisegpt-chat`. Click **Create and Continue**.
3. Skip role assignment → click **Done**.
4. Open the service account → **Keys → Add Key → Create new key** → select **JSON**.  
   A JSON file downloads automatically — store it securely.

### Step 3 — Authorize the service account in Google Chat

Service accounts must be added as members to each Chat space they need to access. In each Google Chat space:

1. Open the space → click its name → **Members → Add people & bots**.
2. Search for the service account email (e.g. `enterprisegpt-chat@project-id.iam.gserviceaccount.com`) and add it.

> **Note:** For broader org-level access, a Workspace admin can also configure the Chat API app via **Google Workspace Admin Console → Apps → Google Chat**.

### tools_config.json entry

```json
"gchat": {
  "enabled": true,
  "config": {
    "credentials_json": "env:GCHAT_CREDENTIALS_JSON"
  }
}
```

> Use `"access_token": "env:GCHAT_ACCESS_TOKEN"` as an alternative if you prefer a short-lived token instead of a service account.

---

## 2. Slack

**Config key:** `slack`  
**Auth type:** Bot User OAuth Token (starts with `xoxb-`)

### Credentials needed

| Key         | Description |
|-------------|-------------|
| `bot_token` | Bot User OAuth Token starting with `xoxb-` |

### Step 1 — Create a Slack App

Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From scratch**. Name it `EnterpriseGPT` and select your workspace.

### Step 2 — Add Bot Token Scopes

Navigate to **OAuth & Permissions → Scopes → Bot Token Scopes**. Add:

```
channels:read    channels:write    channels:history
groups:read      groups:write      groups:history
chat:write       chat:write.public
users:read       reactions:write
im:read          im:write
```

### Step 3 — Install the App to your workspace

Still on the **OAuth & Permissions** page, click **Install to Workspace** and approve. After installation, copy the **Bot User OAuth Token** (starts with `xoxb-`).

### tools_config.json entry

```json
"slack": {
  "enabled": true,
  "config": {
    "bot_token": "env:SLACK_BOT_TOKEN"
  }
}
```

---

## 3. Smartsheet

**Config key:** `smartsheet`  
**Auth type:** Personal Access Token

### Credentials needed

| Key            | Description |
|----------------|-------------|
| `access_token` | Personal Access Token from Smartsheet Account settings |

### Step 1 — Open API Access

Log in to [app.smartsheet.com](https://app.smartsheet.com). Click your avatar (top right) → **Account → Personal Settings → API Access**.

### Step 2 — Generate a new token

Click **Generate new access token**. Name it `EnterpriseGPT`. Copy the token immediately — it is shown only once.

### tools_config.json entry

```json
"smartsheet": {
  "enabled": true,
  "config": {
    "access_token": "env:SMARTSHEET_ACCESS_TOKEN"
  }
}
```

---

## 4. Salesforce

**Config key:** `salesforce`  
**Auth type:** Username + Password + Security Token

### Credentials needed

| Key              | Description |
|------------------|-------------|
| `username`       | Salesforce login email |
| `password`       | Salesforce account password |
| `security_token` | Security token appended to password for API auth |
| `instance_url`   | Your Salesforce org URL, e.g. `https://mycompany.salesforce.com` |

### Step 1 — Ensure API access is enabled for the user

In Salesforce, go to **Setup → Users → Profiles**. Find the profile used for the integration user and confirm **API Enabled** is checked. A System Administrator may need to do this.

### Step 2 — Reset your Security Token

Log in as the integration user → click your avatar → **Settings → My Personal Information → Reset My Security Token**. Salesforce emails the new token to the account email. Copy it from the email.

### Step 3 — Identify your instance URL

The instance URL is shown in your browser when logged in, e.g. `https://mycompany.my.salesforce.com`. Copy the root domain only.

> **Sandbox vs Production:** If using a sandbox, the URL looks like `https://mycompany--sandbox.sandbox.my.salesforce.com`. Use the correct URL for your environment.

### tools_config.json entry

```json
"salesforce": {
  "enabled": true,
  "config": {
    "username": "env:SALESFORCE_USERNAME",
    "password": "env:SALESFORCE_PASSWORD",
    "security_token": "env:SALESFORCE_SECURITY_TOKEN",
    "instance_url": "https://yourorg.my.salesforce.com"
  }
}
```

---

## 5. Zoho CRM

**Config key:** `zoho_crm`  
**Auth type:** Zoho OAuth2 (see [Zoho OAuth2 Setup](#zoho-oauth2-setup-shared-by-4-tools))

### Credentials needed

| Key            | Description |
|----------------|-------------|
| `access_token` | Zoho OAuth2 access token |
| `base_url`     | Data centre API URL, e.g. `https://www.zohoapis.com` |

Required scopes: `ZohoCRM.modules.ALL,ZohoCRM.settings.modules.READ,ZohoCRM.coql.READ`

### tools_config.json entry

```json
"zoho_crm": {
  "enabled": true,
  "config": {
    "access_token": "env:ZOHO_CRM_ACCESS_TOKEN",
    "base_url": "https://www.zohoapis.com"
  }
}
```

---

## 6. Freshdesk

**Config key:** `freshdesk`  
**Auth type:** API Key

### Credentials needed

| Key        | Description |
|------------|-------------|
| `api_key`  | Freshdesk API key from your profile settings |
| `domain`   | Your Freshdesk subdomain, e.g. `mycompany` (without `.freshdesk.com`) |

### Step 1 — Find your API Key

Log in to Freshdesk → click your avatar (top right) → **Profile Settings**. Scroll to the bottom — your API key is shown in the right panel. Click the eye icon to reveal it and copy it.

### Step 2 — Note your subdomain

Your Freshdesk URL when logged in is `https://mycompany.freshdesk.com`. The subdomain is the part before `.freshdesk.com`.

### tools_config.json entry

```json
"freshdesk": {
  "enabled": true,
  "config": {
    "api_key": "env:FRESHDESK_API_KEY",
    "domain": "mycompany"
  }
}
```

---

## 7. Zendesk

**Config key:** `zendesk`  
**Auth type:** API Token + Email

### Credentials needed

| Key         | Description |
|-------------|-------------|
| `subdomain` | Your Zendesk subdomain, e.g. `mycompany` |
| `email`     | Agent email address used for authentication |
| `api_token` | Zendesk API token from Admin Center |

### Step 1 — Enable API Token access

Go to **Admin Center** (gear icon in the sidebar) → **Apps and Integrations → APIs → Zendesk API**. Enable **Token Access** if it is not already on.

### Step 2 — Create a new API Token

Still on the Zendesk API page, click **Add API token**. Enter the description `EnterpriseGPT` and click **Save**. Copy the token — it is shown only once.

### Step 3 — Note your subdomain and agent email

Your Zendesk URL is `https://mycompany.zendesk.com`. The subdomain is `mycompany`. Use the email address of the admin or agent running the integration.

### tools_config.json entry

```json
"zendesk": {
  "enabled": true,
  "config": {
    "subdomain": "mycompany",
    "email": "env:ZENDESK_EMAIL",
    "api_token": "env:ZENDESK_API_TOKEN"
  }
}
```

---

## 8. Zoho Desk

**Config key:** `zoho_desk`  
**Auth type:** Zoho OAuth2 + Org ID (see [Zoho OAuth2 Setup](#zoho-oauth2-setup-shared-by-4-tools))

### Credentials needed

| Key            | Description |
|----------------|-------------|
| `access_token` | Zoho OAuth2 access token |
| `org_id`       | Your Zoho Desk Organization ID |
| `base_url`     | Data centre URL, e.g. `https://desk.zoho.com` |

Required scopes: `Desk.tickets.ALL,Desk.contacts.ALL,Desk.search.READ,Desk.basic.READ`

### Step 1 — Find your Zoho Desk Organization ID

Log in to [desk.zoho.com](https://desk.zoho.com) → **Settings → Developer Space → API**. Your **Organization ID** is shown on this page. Copy it.

### tools_config.json entry

```json
"zoho_desk": {
  "enabled": true,
  "config": {
    "access_token": "env:ZOHO_DESK_ACCESS_TOKEN",
    "org_id": "env:ZOHO_DESK_ORG_ID",
    "base_url": "https://desk.zoho.com"
  }
}
```

---

## 9. Zoho Books

**Config key:** `zoho_books`  
**Auth type:** Zoho OAuth2 + Organization ID (see [Zoho OAuth2 Setup](#zoho-oauth2-setup-shared-by-4-tools))

### Credentials needed

| Key               | Description |
|-------------------|-------------|
| `access_token`    | Zoho OAuth2 access token |
| `organization_id` | Zoho Books Organization ID |
| `base_url`        | Data centre URL, e.g. `https://www.zohoapis.com` |

Required scope: `ZohoBooks.fullaccess.all`

### Step 1 — Find your Zoho Books Organization ID

Log in to [books.zoho.com](https://books.zoho.com) → **Settings → Organization Profile**. The **Organization ID** is shown near the top of this page.

### tools_config.json entry

```json
"zoho_books": {
  "enabled": true,
  "config": {
    "access_token": "env:ZOHO_BOOKS_ACCESS_TOKEN",
    "organization_id": "env:ZOHO_BOOKS_ORG_ID",
    "base_url": "https://www.zohoapis.com"
  }
}
```

---

## 10. Workday

**Config key:** `workday`  
**Auth type:** OAuth2 Client Credentials (machine-to-machine)

### Credentials needed

| Key             | Description |
|-----------------|-------------|
| `base_url`      | Workday REST API base URL, e.g. `https://wd2-impl-services1.workday.com/ccx/api/v1/mycompany` |
| `client_id`     | OAuth2 Client ID from the Workday API Client setup |
| `client_secret` | OAuth2 Client Secret |
| `token_url`     | Token endpoint URL, e.g. `https://wd2-impl-services1.workday.com/ccx/oauth2/mycompany/token` |

### Step 1 — Navigate to API Client setup in Workday

In Workday, search for the task **Register API Client for Integrations**. If you don't see it, search for **Manage → API Clients**.

### Step 2 — Create a new API Client

1. Click **+** to create a new client.
2. Set **Client Name** to `EnterpriseGPT`.
3. Set **Client Grant Type** to `Client Credentials`.
4. Under **Scope (Functional Areas)**, select the areas you need (e.g. `Staffing`, `Organizations`, `Worker Data`).
5. Click **OK**. Copy the **Client ID** and **Client Secret** shown.

### Step 3 — Find your REST API endpoint and token URL

Search for the task **View API Clients**. Select your new client. The **Workday REST API Endpoint** and **Token Endpoint** are displayed on the details page. Copy both.

### tools_config.json entry

```json
"workday": {
  "enabled": true,
  "config": {
    "base_url": "https://wd2-impl-services1.workday.com/ccx/api/v1/mycompany",
    "client_id": "env:WORKDAY_CLIENT_ID",
    "client_secret": "env:WORKDAY_CLIENT_SECRET",
    "token_url": "https://wd2-impl-services1.workday.com/ccx/oauth2/mycompany/token"
  }
}
```

---

## 11. BambooHR

**Config key:** `bamboohr`  
**Auth type:** API Key

### Credentials needed

| Key              | Description |
|------------------|-------------|
| `api_key`        | BambooHR API key from your profile settings |
| `company_domain` | Your BambooHR subdomain, e.g. `mycompany` (without `.bamboohr.com`) |

### Step 1 — Open API Keys in BambooHR

Log in to BambooHR → click your name in the top right → **API Keys**.

### Step 2 — Generate a new API key

Click **Add New Key**. Enter a label like `EnterpriseGPT` and click **Generate Key**. Copy the key — you won't be able to see it again.

### Step 3 — Note your company subdomain

Your BambooHR URL is `https://mycompany.bamboohr.com`. The subdomain is `mycompany`.

### tools_config.json entry

```json
"bamboohr": {
  "enabled": true,
  "config": {
    "api_key": "env:BAMBOOHR_API_KEY",
    "company_domain": "env:BAMBOOHR_COMPANY_DOMAIN"
  }
}
```

---

## 12. Zoho People

**Config key:** `zoho_people`  
**Auth type:** Zoho OAuth2 (see [Zoho OAuth2 Setup](#zoho-oauth2-setup-shared-by-4-tools))

### Credentials needed

| Key            | Description |
|----------------|-------------|
| `access_token` | Zoho OAuth2 access token |
| `base_url`     | Data centre URL, e.g. `https://people.zoho.com` |

Required scopes: `ZOHOPEOPLE.employee.ALL,ZOHOPEOPLE.leave.ALL,ZOHOPEOPLE.org.READ`

### tools_config.json entry

```json
"zoho_people": {
  "enabled": true,
  "config": {
    "access_token": "env:ZOHO_PEOPLE_ACCESS_TOKEN",
    "base_url": "https://people.zoho.com"
  }
}
```

---

## 13. Rippling

**Config key:** `rippling`  
**Auth type:** API Key

### Credentials needed

| Key       | Description |
|-----------|-------------|
| `api_key` | Rippling API key from the Platform API app |

### Step 1 — Install the Platform API app

Log in to [app.rippling.com](https://app.rippling.com) as an Administrator. Go to **App Shop** and search for **Rippling Platform API**. Install the app and approve the requested permissions (employees:read, employees:write, departments:read, groups:read).

### Step 2 — Generate an API Key

Go to **Settings → Rippling Platform API** (or navigate from the installed app). Click **Generate API Key**. Name it `EnterpriseGPT`. Copy the key immediately.

> 🔴 **Important:** The Rippling API key has administrator-level permissions. Store it only in Secret Manager or an equivalent secrets store — never in plaintext config files.

### tools_config.json entry

```json
"rippling": {
  "enabled": true,
  "config": {
    "api_key": "env:RIPPLING_API_KEY"
  }
}
```

---

## Delivery Checklist

Use this table to verify each connector before going live:

| Connector   | Env Variables to Set                                            | Verification Call |
|-------------|------------------------------------------------------------------|-------------------|
| Google Chat | `GCHAT_CREDENTIALS_JSON`                                        | `list_gchat_spaces()` |
| Slack       | `SLACK_BOT_TOKEN`                                               | `list_slack_channels()` |
| Smartsheet  | `SMARTSHEET_ACCESS_TOKEN`                                       | `list_smartsheet_sheets()` |
| Salesforce  | `SALESFORCE_USERNAME`, `SALESFORCE_PASSWORD`, `SALESFORCE_SECURITY_TOKEN` | `list_salesforce_records("Lead")` |
| Zoho CRM    | `ZOHO_CRM_ACCESS_TOKEN`                                         | `list_zoho_crm_modules()` |
| Freshdesk   | `FRESHDESK_API_KEY`                                             | `list_freshdesk_tickets()` |
| Zendesk     | `ZENDESK_EMAIL`, `ZENDESK_API_TOKEN`                            | `list_zendesk_groups()` |
| Zoho Desk   | `ZOHO_DESK_ACCESS_TOKEN`, `ZOHO_DESK_ORG_ID`                   | `list_zoho_desk_departments()` |
| Zoho Books  | `ZOHO_BOOKS_ACCESS_TOKEN`, `ZOHO_BOOKS_ORG_ID`                 | `list_zoho_books_contacts()` |
| Workday     | `WORKDAY_CLIENT_ID`, `WORKDAY_CLIENT_SECRET`                    | `list_workday_workers(limit=1)` |
| BambooHR    | `BAMBOOHR_API_KEY`, `BAMBOOHR_COMPANY_DOMAIN`                   | `list_bamboohr_employees()` |
| Zoho People | `ZOHO_PEOPLE_ACCESS_TOKEN`                                      | `list_zoho_people_employees()` |
| Rippling    | `RIPPLING_API_KEY`                                              | `list_rippling_employees()` |

---

## Secret Storage Convention

All credentials should be stored in **Google Secret Manager** (or your org's approved secrets store) and referenced in `tools_config.json` using the `env:` prefix:

```json
"api_key": "env:FRESHDESK_API_KEY"
```

The `env:` prefix instructs the config loader to read the value from the environment variable at runtime, keeping secrets out of version control.

For Cloud Run deployments, mount secrets as environment variables via the `--set-secrets` flag in your deploy script.
