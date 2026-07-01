#!/bin/bash
# Deploy stratova-web-scraper-mcp to Cloud Run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

PROJECT_ID="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-ninth-archway-496404-s2}}"
REGION="${GCP_REGION:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
SERVICE_NAME="stratova-web-scraper-mcp"
IMAGE="us-central1-docker.pkg.dev/${PROJECT_ID}/stratova-mcp/${SERVICE_NAME}:latest"

# Gemini Enterprise Website data store ID for scrape ingestion
WEB_SCRAPER_DS_ID="${WEB_SCRAPER_DS_ID:-}"

source "$REPO_ROOT/deployment/secret_utils.sh"

echo "Authenticating Docker to Artifact Registry..."
gcloud auth application-default print-access-token | \
  docker login -u oauth2accesstoken --password-stdin us-central1-docker.pkg.dev

echo "Building image for linux/amd64..."
docker build --platform linux/amd64 -t "${IMAGE}" "${SCRIPT_DIR}"

echo "Pushing image..."
docker push "${IMAGE}"

echo "Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --no-allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GEMINI_PROJECT_ID=${PROJECT_ID},WEB_SCRAPER_DS_ID=${WEB_SCRAPER_DS_ID}" \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 5

echo "Deployed. URL:"
SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" \
  --region "${REGION}" --project "${PROJECT_ID}" --format "value(status.url)")"
echo "${SERVICE_URL}"

save_secret "laabu-mcp-web-scraper-url" "${SERVICE_URL}" "${PROJECT_ID}"
