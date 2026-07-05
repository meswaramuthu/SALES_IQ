#!/usr/bin/env bash
# Deploy Ops IQ scheduled checks as a Cloud Run Job + Cloud Scheduler.
#
# Creates:
#   - Artifact Registry repo (if missing)
#   - Cloud Run Job: ops-iq-checker
#   - Cloud Scheduler job: ops-iq-daily-report   (daily 08:00 UTC)
#   - Cloud Scheduler job: ops-iq-alert-check    (every 2 hours)
#
# Usage:
#   cd agents/ops-iq/OpsIQ
#   bash deploy/sync_deploy.sh
#
# Prerequisites:
#   gcloud auth login
#   gcloud config set project ninth-archway-496404-s2
#   APIs enabled: run.googleapis.com, cloudscheduler.googleapis.com,
#                 artifactregistry.googleapis.com

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT="${GOOGLE_CLOUD_PROJECT:-ninth-archway-496404-s2}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
REPO="stratova-agents"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/ops-iq-checker:latest"
JOB_NAME="ops-iq-checker"
SA="${PROJECT}@appspot.gserviceaccount.com"   # or your dedicated service account

# Alert recipients — comma-separated, matches ALERT_TO_EMAILS env var
ALERT_TO_EMAILS="abdul@stratova.ai,ops@stratova.ai"

# Email agent deployed on Vertex AI
EMAIL_AGENT_RESOURCE_NAME="projects/528271267622/locations/us-central1/reasoningEngines/8927971195622522880"

# ── Ensure required APIs are enabled ─────────────────────────────────────────
echo "▶ Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  --project="${PROJECT}" --quiet

# ── Artifact Registry ─────────────────────────────────────────────────────────
echo "▶ Ensuring Artifact Registry repo exists..."
gcloud artifacts repositories describe "${REPO}" \
  --location="${REGION}" --project="${PROJECT}" &>/dev/null || \
gcloud artifacts repositories create "${REPO}" \
  --repository-format=docker \
  --location="${REGION}" \
  --project="${PROJECT}" \
  --description="Stratova AI agent Docker images"

# ── Build & push image ────────────────────────────────────────────────────────
echo "▶ Building image: ${IMAGE}"
# Build from repo root (laabu-ai-app/) so Dockerfile can COPY agents/ and tools/
cd "$(git rev-parse --show-toplevel)"
gcloud builds submit \
  --tag="${IMAGE}" \
  --project="${PROJECT}" \
  --config=cloudbuild.yaml . || \
gcloud builds submit \
  --tag="${IMAGE}" \
  --project="${PROJECT}" \
  --dockerfile="agents/ops-iq/OpsIQ/scheduler/Dockerfile" \
  .

# ── Cloud Run Job ─────────────────────────────────────────────────────────────
echo "▶ Deploying Cloud Run Job: ${JOB_NAME}"
gcloud run jobs deploy "${JOB_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --service-account="${SA}" \
  --max-retries=1 \
  --task-timeout=300 \
  --set-env-vars="\
GOOGLE_CLOUD_PROJECT=${PROJECT},\
GOOGLE_CLOUD_LOCATION=${REGION},\
GOOGLE_GENAI_USE_VERTEXAI=True,\
EMAIL_AGENT_RESOURCE_NAME=${EMAIL_AGENT_RESOURCE_NAME},\
ALERT_TO_EMAILS=${ALERT_TO_EMAILS},\
ALERT_FROM_NAME=Ops IQ — Stratova AI,\
FIRESTORE_USAGE_COLLECTION=ops_iq_usage,\
CONFIG_CACHE_TTL_SECONDS=0,\
TOOLS_CONFIG_GCS_URI=gs://stratova-platform/agents/ops-iq/config/tools_config.json"

# ── Cloud Scheduler: daily status report ─────────────────────────────────────
# 08:00 UTC = 13:30 IST
echo "▶ Creating scheduler job: ops-iq-daily-report (08:00 UTC daily)"
gcloud scheduler jobs delete ops-iq-daily-report \
  --location="${REGION}" --project="${PROJECT}" --quiet 2>/dev/null || true

gcloud scheduler jobs create http ops-iq-daily-report \
  --location="${REGION}" \
  --project="${PROJECT}" \
  --schedule="0 8 * * *" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB_NAME}:run" \
  --message-body="{\"overrides\":{\"containerOverrides\":[{\"args\":[\"--report\",\"--hours\",\"24\"]}]}}" \
  --oauth-service-account-email="${SA}" \
  --description="Ops IQ daily platform status report email (08:00 UTC)"

# ── Cloud Scheduler: alert check every 2 hours ───────────────────────────────
echo "▶ Creating scheduler job: ops-iq-alert-check (every 2 hours)"
gcloud scheduler jobs delete ops-iq-alert-check \
  --location="${REGION}" --project="${PROJECT}" --quiet 2>/dev/null || true

gcloud scheduler jobs create http ops-iq-alert-check \
  --location="${REGION}" \
  --project="${PROJECT}" \
  --schedule="0 */2 * * *" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB_NAME}:run" \
  --message-body="{\"overrides\":{\"containerOverrides\":[{\"args\":[\"--hours\",\"1\"]}]}}" \
  --oauth-service-account-email="${SA}" \
  --description="Ops IQ threshold alert check (every 2h, emails only on violations)"

echo ""
echo "✅ Setup complete."
echo ""
echo "Jobs created:"
gcloud scheduler jobs list --location="${REGION}" --project="${PROJECT}" \
  --filter="name~ops-iq" --format="table(name,schedule,state)"
echo ""
echo "Test the daily report now:"
echo "  gcloud run jobs execute ops-iq-checker --region=${REGION} --project=${PROJECT} \\"
echo "    --args='--report,--hours,24'"
echo ""
echo "Test the alert check now:"
echo "  gcloud run jobs execute ops-iq-checker --region=${REGION} --project=${PROJECT} \\"
echo "    --args='--hours,1'"
