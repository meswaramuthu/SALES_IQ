#!/bin/bash
# Deploy stratova-calendar-mcp to Cloud Run
# Uses Docker build+push (works with ADC when Cloud Build needs user creds)
set -e
PROJECT_ID=${GOOGLE_CLOUD_PROJECT:-ninth-archway-496404-s2}
REGION=${GOOGLE_CLOUD_LOCATION:-us-central1}
IMAGE="us-central1-docker.pkg.dev/${PROJECT_ID}/stratova-mcp/stratova-calendar-mcp:latest"

# Required: SA key stored in GCS + calendar owner to impersonate via DWD
GMAIL_SA_KEY_GCS_URI=${GMAIL_SA_KEY_GCS_URI:-gs://ninth-archway-496404-s2-knowledge-iq/creds/google-sa.json}
GMAIL_USER_EMAIL=${GMAIL_USER_EMAIL:-abdul@stratova.ai}
SALESPERSON_CALENDAR_ID=${SALESPERSON_CALENDAR_ID:-primary}

echo "Authenticating Docker to Artifact Registry..."
gcloud auth application-default print-access-token | \
  docker login -u oauth2accesstoken --password-stdin us-central1-docker.pkg.dev

echo "Building image for linux/amd64..."
docker build --platform linux/amd64 -t "${IMAGE}" .

echo "Pushing image..."
docker push "${IMAGE}"

echo "Deploying to Cloud Run..."
gcloud run deploy stratova-calendar-mcp \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GMAIL_SA_KEY_GCS_URI=${GMAIL_SA_KEY_GCS_URI},GMAIL_USER_EMAIL=${GMAIL_USER_EMAIL},SALESPERSON_CALENDAR_ID=${SALESPERSON_CALENDAR_ID}" \
  --service-account "hr-scheduler@${PROJECT_ID}.iam.gserviceaccount.com" \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 5 \
  --timeout 300

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$REPO_ROOT/deployment/secret_utils.sh"

echo "Deployed. URL:"
SERVICE_URL="$(gcloud run services describe stratova-calendar-mcp \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --format "value(status.url)")"
echo "${SERVICE_URL}"

save_secret "laabu-mcp-calendar-url" "${SERVICE_URL}" "${PROJECT_ID}"
