#!/usr/bin/env bash
# Bootstrap GCP infrastructure dependencies required before any deployment.
# Creates:
#   1. Enables all required GCP APIs
#   2. GCS bucket          — config + state storage
#   3. Artifact Registry   — Docker image repository for Cloud Run
#
# Usage:
#   ./deployment/setup_infra.sh
#
# Required env vars:
#   GCP_PROJECT             — GCP project ID
#   GCS_BUCKET              — GCS bucket name to create
#   ARTIFACT_REGISTRY_REPO  — Artifact Registry repo name (e.g. laabu-repo)
#
# Optional env vars:
#   GCP_REGION              — Region (default: us-central1)
#   GCS_BUCKET_LOCATION     — Bucket location (default: same as GCP_REGION)

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
export GCP_PROJECT="${GCP_PROJECT:-}"
export GCP_REGION="${GCP_REGION:-us-central1}"
export GCS_BUCKET="${GCS_BUCKET:-}"
export ARTIFACT_REGISTRY_REPO="${ARTIFACT_REGISTRY_REPO:-}"
GCS_BUCKET_LOCATION="${GCS_BUCKET_LOCATION:-$GCP_REGION}"

# ── Validation ────────────────────────────────────────────────────────────────
if [[ -z "$GCP_PROJECT" ]]; then
  echo "ERROR: GCP_PROJECT must be set."
  echo "  export GCP_PROJECT=your-project-id"
  exit 1
fi

if [[ -z "$GCS_BUCKET" ]]; then
  echo "ERROR: GCS_BUCKET must be set."
  echo "  export GCS_BUCKET=your-bucket-name"
  exit 1
fi

if [[ -z "$ARTIFACT_REGISTRY_REPO" ]]; then
  echo "ERROR: ARTIFACT_REGISTRY_REPO must be set."
  echo "  export ARTIFACT_REGISTRY_REPO=your-repo-name"
  exit 1
fi

# ── Helpers ───────────────────────────────────────────────────────────────────
info()    { echo "[INFO]  $*"; }
success() { echo "[OK]    $*"; }
error()   { echo "[ERROR] $*" >&2; exit 1; }

require() {
  command -v "$1" &>/dev/null || error "'$1' is not installed or not in PATH."
}

require gcloud
require gsutil

echo "============================================"
echo " Laabu — GCP Infrastructure Setup"
echo " Project  : $GCP_PROJECT"
echo " Region   : $GCP_REGION"
echo " Bucket   : $GCS_BUCKET  (location: $GCS_BUCKET_LOCATION)"
echo " Registry : $ARTIFACT_REGISTRY_REPO"
echo "============================================"
echo ""

# ── 1. Set active project ─────────────────────────────────────────────────────
info "Setting active project to '$GCP_PROJECT'…"
gcloud config set project "$GCP_PROJECT"
success "Active project set."

# ── 2. Enable required APIs ───────────────────────────────────────────────────
info "Enabling required GCP APIs…"
gcloud services enable \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  aiplatform.googleapis.com \
  discoveryengine.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  --project="$GCP_PROJECT"
success "APIs enabled."

# ── 3. GCS Bucket ─────────────────────────────────────────────────────────────
info "Checking GCS bucket 'gs://$GCS_BUCKET'…"
if gsutil ls -b "gs://$GCS_BUCKET" &>/dev/null; then
  success "Bucket 'gs://$GCS_BUCKET' already exists — skipping."
else
  info "Creating bucket 'gs://$GCS_BUCKET' in '$GCS_BUCKET_LOCATION'…"
  gsutil mb \
    -p "$GCP_PROJECT" \
    -l "$GCS_BUCKET_LOCATION" \
    -b on \
    "gs://$GCS_BUCKET"
  success "Bucket 'gs://$GCS_BUCKET' created."
fi

# ── 4. Artifact Registry ──────────────────────────────────────────────────────
info "Checking Artifact Registry repo '$ARTIFACT_REGISTRY_REPO'…"
if gcloud artifacts repositories describe "$ARTIFACT_REGISTRY_REPO" \
     --location="$GCP_REGION" \
     --project="$GCP_PROJECT" &>/dev/null; then
  success "Artifact Registry repo '$ARTIFACT_REGISTRY_REPO' already exists — skipping."
else
  info "Creating Artifact Registry repo '$ARTIFACT_REGISTRY_REPO'…"
  gcloud artifacts repositories create "$ARTIFACT_REGISTRY_REPO" \
    --repository-format=docker \
    --location="$GCP_REGION" \
    --project="$GCP_PROJECT" \
    --description="Laabu Cloud Run service images"
  success "Artifact Registry repo '$ARTIFACT_REGISTRY_REPO' created."
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo " Infrastructure setup complete."
echo ""
echo " Full Artifact Registry URL:"
echo "   $GCP_REGION-docker.pkg.dev/$GCP_PROJECT/$ARTIFACT_REGISTRY_REPO"
echo ""
echo " Use this as ARTIFACT_REGISTRY_REPO when running deploy_cloudrun.sh"
echo "============================================"
