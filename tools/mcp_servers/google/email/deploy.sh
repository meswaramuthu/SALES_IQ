#!/bin/bash
# Deploy stratova-email-mcp to Cloud Run
set -e
PROJECT_ID=${GOOGLE_CLOUD_PROJECT:-ninth-archway-496404-s2}
REGION=${GOOGLE_CLOUD_LOCATION:-us-central1}
IMAGE="gcr.io/${PROJECT_ID}/stratova-email-mcp:latest"

echo "Building and deploying stratova-email-mcp..."
gcloud builds submit --tag "${IMAGE}" .
gcloud run deploy stratova-email-mcp \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --no-allow-unauthenticated \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 5

echo "Deployed. URL:"
gcloud run services describe stratova-email-mcp --region ${REGION} --format "value(status.url)"
