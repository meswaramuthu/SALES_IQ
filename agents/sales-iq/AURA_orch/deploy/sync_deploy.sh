#!/usr/bin/env bash
# Deploy the Knowledge IQ Sync service to GCP.
#
# Deploys:
#   1. Docker image → Artifact Registry
#   2. Cloud Run Job  (scheduler.job)            — runs on SYNC_SCHEDULE (default: hourly)
#   3. Cloud Run Service (scheduler.webhook_server) — receives push events from SharePoint / GitHub
#   4. Cloud Scheduler → triggers the Cloud Run Job on cron
#
# Prerequisites:
#   gcloud auth login && gcloud auth configure-docker <REGION>-docker.pkg.dev
#   Secret Manager secrets must exist: SHAREPOINT_CLIENT_SECRET, GITHUB_TOKEN,
#   SYNC_GITHUB_WEBHOOK_SECRET (if using GitHub webhooks)
#
# Usage:
#   cd agents/knowledge-iq/enterpriseGPT
#   export GCP_PROJECT=ninth-archway-496404-s2
#   export RAG_CORPUS="projects/.../locations/.../ragCorpora/..."
#   export SYNC_STATE_GCS_URI="gs://my-bucket/knowledge-iq/sync-state.json"
#   export TOOLS_CONFIG_GCS_URI="gs://my-bucket/knowledge-iq/tools_config.json"
#   bash deploy/sync_deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTERPRISE_GPT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"   # agents/knowledge-iq/enterpriseGPT/

# ── Required ─────────────────────────────────────────────────────────────────
: "${GCP_PROJECT:?Set GCP_PROJECT}"
: "${RAG_CORPUS:?Set RAG_CORPUS}"
: "${SYNC_STATE_GCS_URI:?Set SYNC_STATE_GCS_URI}"
: "${TOOLS_CONFIG_GCS_URI:?Set TOOLS_CONFIG_GCS_URI}"

# ── Optional (sensible defaults) ─────────────────────────────────────────────
REGION="${GCP_REGION:-us-central1}"
REGISTRY="${GCP_REGION:-us-central1}-docker.pkg.dev"
REPO="${ARTIFACT_REPO:-knowledge-iq}"
IMAGE="${REGISTRY}/${GCP_PROJECT}/${REPO}/sync:latest"
JOB_NAME="${SYNC_JOB_NAME:-knowledge-iq-sync-job}"
WEBHOOK_SVC="${SYNC_WEBHOOK_SVC:-knowledge-iq-sync-webhook}"
SCHEDULE="${SYNC_SCHEDULE:-0 * * * *}"     # hourly by default
SA_EMAIL="${SYNC_SA_EMAIL:-}"              # optional: Workload Identity / SA email

# Site/repo overrides (optional — defaults are read from tools_config.json)
SYNC_SHAREPOINT_SITES="${SYNC_SHAREPOINT_SITES:-}"
SYNC_GITHUB_REPOS="${SYNC_GITHUB_REPOS:-}"

# ── Ensure required secrets exist in Secret Manager ──────────────────────────
# Creates a placeholder if the secret is absent so --set-secrets never 404s.
# Replace placeholder values via:
#   gcloud secrets versions add SECRET_NAME --data-file=- <<< "real-value"
_ensure_secret() {
  local name="$1"
  local default_val="${2:-placeholder}"
  if ! gcloud secrets describe "${name}" --project="${GCP_PROJECT}" &>/dev/null; then
    echo "  [Secret Manager] '${name}' not found — creating with placeholder. Update with real value before use."
    printf '%s' "${default_val}" | gcloud secrets create "${name}" \
      --data-file=- \
      --replication-policy="automatic" \
      --project="${GCP_PROJECT}"
  else
    echo "  [Secret Manager] '${name}' already exists."
  fi
}

echo "▶ Ensuring secrets exist in project ${GCP_PROJECT}..."
_ensure_secret "SHAREPOINT_CLIENT_SECRET"
_ensure_secret "GITHUB_TOKEN"
_ensure_secret "SYNC_GITHUB_WEBHOOK_SECRET"

echo "▶ Building image: ${IMAGE}"
# Build from enterpriseGPT/ so scheduler/ package is at the Docker build context root
docker build -t "${IMAGE}" -f "${ENTERPRISE_GPT_DIR}/scheduler/Dockerfile" "${ENTERPRISE_GPT_DIR}"

echo "▶ Pushing image"
docker push "${IMAGE}"

# ── Helper: build --set-env-vars string ──────────────────────────────────────
COMMON_ENV="TOOLS_CONFIG_GCS_URI=${TOOLS_CONFIG_GCS_URI},\
RAG_CORPUS=${RAG_CORPUS},\
SYNC_STATE_GCS_URI=${SYNC_STATE_GCS_URI}"
[[ -n "${SYNC_SHAREPOINT_SITES}" ]] && COMMON_ENV+=",SYNC_SHAREPOINT_SITES=${SYNC_SHAREPOINT_SITES}"
[[ -n "${SYNC_GITHUB_REPOS}" ]]     && COMMON_ENV+=",SYNC_GITHUB_REPOS=${SYNC_GITHUB_REPOS}"

SA_FLAG=""
[[ -n "${SA_EMAIL}" ]] && SA_FLAG="--service-account=${SA_EMAIL}"

# ── Cloud Run Job ─────────────────────────────────────────────────────────────
echo "▶ Deploying Cloud Run Job: ${JOB_NAME}"
if gcloud run jobs describe "${JOB_NAME}" --region="${REGION}" &>/dev/null; then
    gcloud run jobs update "${JOB_NAME}" \
        --image="${IMAGE}" \
        --region="${REGION}" \
        --set-env-vars="${COMMON_ENV}" \
        --set-secrets="SHAREPOINT_CLIENT_SECRET=SHAREPOINT_CLIENT_SECRET:latest,GITHUB_TOKEN=GITHUB_TOKEN:latest" \
        ${SA_FLAG}
else
    gcloud run jobs create "${JOB_NAME}" \
        --image="${IMAGE}" \
        --region="${REGION}" \
        --set-env-vars="${COMMON_ENV}" \
        --set-secrets="SHAREPOINT_CLIENT_SECRET=SHAREPOINT_CLIENT_SECRET:latest,GITHUB_TOKEN=GITHUB_TOKEN:latest" \
        --task-timeout=3600 \
        --max-retries=2 \
        ${SA_FLAG}
fi

# ── Cloud Scheduler ───────────────────────────────────────────────────────────
_PROJ_NUM=$(gcloud projects describe "${GCP_PROJECT}" --format='value(projectNumber)')
SCHEDULER_SA="${SA_EMAIL:-${_PROJ_NUM}-compute@developer.gserviceaccount.com}"
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${GCP_PROJECT}/jobs/${JOB_NAME}:run"

echo "▶ Configuring Cloud Scheduler: ${SCHEDULE}"
if gcloud scheduler jobs describe "${JOB_NAME}-trigger" --location="${REGION}" &>/dev/null; then
    gcloud scheduler jobs update http "${JOB_NAME}-trigger" \
        --location="${REGION}" \
        --schedule="${SCHEDULE}" \
        --uri="${JOB_URI}" \
        --message-body='{}' \
        --oauth-service-account-email="${SCHEDULER_SA}"
else
    gcloud scheduler jobs create http "${JOB_NAME}-trigger" \
        --location="${REGION}" \
        --schedule="${SCHEDULE}" \
        --uri="${JOB_URI}" \
        --message-body='{}' \
        --oauth-service-account-email="${SCHEDULER_SA}"
fi

# ── Cloud Run Service (webhook receiver) ──────────────────────────────────────
echo "▶ Deploying Webhook Service: ${WEBHOOK_SVC}"
WEBHOOK_ENV="${COMMON_ENV},SYNC_SP_CLIENT_STATE=${SYNC_SP_CLIENT_STATE:-stratova-sync-v1}"

gcloud run deploy "${WEBHOOK_SVC}" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --command="python" \
    --args="-m,scheduler.webhook_server" \
    --allow-unauthenticated \
    --set-env-vars="${WEBHOOK_ENV}" \
    --set-secrets="SHAREPOINT_CLIENT_SECRET=SHAREPOINT_CLIENT_SECRET:latest,\
GITHUB_TOKEN=GITHUB_TOKEN:latest,\
SYNC_GITHUB_WEBHOOK_SECRET=SYNC_GITHUB_WEBHOOK_SECRET:latest" \
    ${SA_FLAG}

WEBHOOK_URL=$(gcloud run services describe "${WEBHOOK_SVC}" \
    --region="${REGION}" \
    --format="value(status.url)")

echo ""
echo "════════════════════════════════════════════════"
echo "  Deployment complete!"
echo "════════════════════════════════════════════════"
echo ""
echo "  Cron job:  ${JOB_NAME}  (${SCHEDULE})"
echo "  Webhook:   ${WEBHOOK_URL}"
echo ""
echo "  Register these webhook URLs:"
echo ""
echo "  SharePoint (Graph subscription resource: drives/{driveId}/root):"
echo "    ${WEBHOOK_URL}/webhook/sharepoint"
echo ""
echo "  GitHub (Repository Settings → Webhooks → push events):"
echo "    ${WEBHOOK_URL}/webhook/github"
echo ""
echo "  The cron job will auto-register and renew SharePoint subscriptions"
echo "  after you set webhook_base_url in tools_config.json → sharepoint.config."
echo "════════════════════════════════════════════════"
