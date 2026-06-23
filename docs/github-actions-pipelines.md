# GitHub Actions Pipelines — How to Run

All pipelines are triggered manually via **GitHub Actions > workflow_dispatch**. There is no automatic trigger on push.

---

## Prerequisites — GitHub Secrets

Before running any pipeline, ensure this secret is configured in your repository:
**Settings → Secrets and variables → Actions → New repository secret**

| Secret | Description |
|--------|-------------|
| `GCP_SA_KEY` | GCP service account JSON key (the full contents of the downloaded `.json` key file) |

**How to get the service account JSON key:**
1. Go to GCP Console → IAM & Admin → Service Accounts
2. Select your service account (or create one with the required roles)
3. Keys tab → Add Key → Create new key → JSON → Download
4. Copy the entire contents of the downloaded `.json` file as the secret value

> All other inputs (project ID, bucket, etc.) are entered at run time via the workflow form.

---

## How to trigger any pipeline

1. Go to your GitHub repository
2. Click the **Actions** tab
3. Select the workflow from the left sidebar
4. Click **Run workflow** (top right of the run list)
5. Fill in the form fields
6. Click the green **Run workflow** button

---

## Pipeline 1 — Deploy to GCP

**File:** `.github/workflows/deploy.yml`
**What it does:** Deploys the Knowledge IQ / enterpriseGPT agent stack and/or Cloud Run services.

### Inputs

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| GCP Project ID | yes | — | Your GCP project ID |
| GCP Region | yes | `us-central1` | Region for deployment |
| GCS Bucket name | yes | — | GCS bucket for config and state |
| Artifact Registry repo URL | no | — | Required only for Cloud Run image deployments |
| Deploy target | yes | `all` | `all` — run both jobs; `agent` — agent stack only; `cloudrun` — Cloud Run only |
| Cloud Run flags | no | — | Pass `--scheduler` or `--mcp` to run only that part of the Cloud Run deployment |

### Jobs

```
deploy-agent  →  deploy-cloudrun
```

- **deploy-agent**: Installs Python deps, runs `deployment/deploy_agent.sh` (deploys Agent Engine, Vertex AI RAG corpus, GCS config)
- **deploy-cloudrun**: Runs after `deploy-agent`, runs `deployment/deploy_cloudrun.sh` (deploys Cloud Run scheduler jobs and MCP tool servers)

### Example — deploy everything

| Field | Value |
|-------|-------|
| GCP Project ID | `ninth-archway-496404-s2` |
| GCP Region | `us-central1` |
| GCS Bucket name | `laabu-agent-config` |
| Deploy target | `all` |

### Example — deploy only Cloud Run scheduler

| Field | Value |
|-------|-------|
| Deploy target | `cloudrun` |
| Cloud Run flags | `--scheduler` |

---

## Pipeline 2 — Manage Gemini Enterprise App

**File:** `.github/workflows/gemini-enterprise-app.yml`
**What it does:** Creates or deletes a Gemini Enterprise app in Vertex AI Agent Builder.

### Inputs

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| GCP Project ID | yes | — | Your GCP project ID |
| App name | yes | `stratova-gemini` | Name of the Gemini Enterprise app |
| Location | yes | `global` | Location for the app |
| Action | yes | `create` | `create` — create the app; `--delete` — delete the app |

### Example — create app

| Field | Value |
|-------|-------|
| GCP Project ID | `ninth-archway-496404-s2` |
| App name | `stratova-gemini` |
| Location | `global` |
| Action | `create` |

### Example — delete app

| Field | Value |
|-------|-------|
| Action | `--delete` |

> If the app already exists, the create action exits cleanly with "App already exists." (HTTP 409).

---

## Pipeline 3 — Create Gemini Enterprise Agent

**File:** `.github/workflows/gemini-enterprise-agent.yml`
**What it does:** Creates an agent inside an existing Gemini Enterprise app.

> Run **Pipeline 2** (create app) before this one — the agent requires an existing Engine ID.

### Inputs

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| GCP Project ID | yes | — | Your GCP project ID |
| Engine ID | yes | — | Engine ID of the Gemini Enterprise app (e.g. `gemini-enterprise-app_1781176722287`) |
| Agent display name | yes | — | Human-readable name for the agent |
| Agent description | yes | — | What the agent does |
| Reasoning Engine resource path | no | — | Full path if linking a Vertex AI Reasoning Engine (e.g. `projects/123/locations/us-central1/reasoningEngines/456`) |

### How to find the Engine ID

After running Pipeline 2, the Engine ID appears in the GCP console:
```
https://console.cloud.google.com/gen-app-builder/apps?project=<YOUR_PROJECT>
```
Copy the ID shown under your app name.

### Example — create agent without reasoning engine

| Field | Value |
|-------|-------|
| GCP Project ID | `ninth-archway-496404-s2` |
| Engine ID | `gemini-enterprise-app_1781176722287` |
| Agent display name | `Knowledge IQ Agent` |
| Agent description | `Answers enterprise knowledge queries using RAG` |
| Reasoning Engine resource path | *(leave blank)* |

### Example — create agent with reasoning engine

| Field | Value |
|-------|-------|
| Reasoning Engine resource path | `projects/528271267622/locations/us-central1/reasoningEngines/2775842998401892352` |

---

## Recommended run order (first-time setup)

```
1. Pipeline 4  →  Setup GCP Infrastructure  (bucket, registry, APIs)
2. Pipeline 2  →  Create the Gemini Enterprise App
3. Pipeline 3  →  Create the agent inside the app
4. Pipeline 1  →  Deploy the full agent stack + Cloud Run services
```

---

## Pipeline 4 — Setup GCP Infrastructure

**File:** `.github/workflows/setup-infra.yml`
**What it does:** One-time bootstrap that enables all required GCP APIs, creates the GCS bucket, and creates the Artifact Registry repository. Safe to re-run — existing resources are skipped.

### Inputs

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| GCP Project ID | yes | — | Your GCP project ID |
| GCP Region | yes | `us-central1` | Region for Artifact Registry and Cloud Run |
| GCS Bucket name | yes | — | Bucket name to create (used by all deploy scripts) |
| Artifact Registry repo name | yes | — | Repo name to create (e.g. `laabu-repo`) |
| GCS Bucket location | no | same as region | Override bucket location if needed |

### APIs enabled by this pipeline

- `storage.googleapis.com`
- `artifactregistry.googleapis.com`
- `run.googleapis.com`
- `aiplatform.googleapis.com`
- `discoveryengine.googleapis.com`
- `cloudbuild.googleapis.com`
- `iam.googleapis.com`

### Output

After running, the job prints the full Artifact Registry URL to use as `ARTIFACT_REGISTRY_REPO` in Pipeline 1:

```
us-central1-docker.pkg.dev/<PROJECT_ID>/<REPO_NAME>
```
