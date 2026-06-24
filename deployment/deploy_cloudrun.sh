#!/usr/bin/env bash
# Central entry point: deploy all Cloud Run services.
# Covers:
#   1. Scheduler jobs  — Knowledge IQ sync service (Cloud Run Job + Webhook Service)
#   2. MCP tools       — all MCP server Cloud Run services
#
# Usage:
#   ./deployment/deploy_cloudrun.sh           # deploy everything
#   ./deployment/deploy_cloudrun.sh --scheduler
#   ./deployment/deploy_cloudrun.sh --mcp

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MCP_DIR="$REPO_ROOT/tools/mcp_servers"

DEPLOY_SCHEDULER=true
DEPLOY_MCP=true

for arg in "$@"; do
  case $arg in
    --scheduler) DEPLOY_MCP=false ;;
    --mcp)       DEPLOY_SCHEDULER=false ;;
  esac
done

# --- Required env vars ---
export GCP_PROJECT="${GCP_PROJECT:-}"
export GCP_REGION="${GCP_REGION:-us-central1}"
export GCS_BUCKET="${GCS_BUCKET:-}"

if [[ -z "$GCP_PROJECT" ]]; then
  echo "ERROR: GCP_PROJECT must be set."
  echo "  export GCP_PROJECT=your-project-id"
  exit 1
fi

echo "============================================"
echo " Cloud Run Deployment"
echo " Project : $GCP_PROJECT"
echo " Region  : $GCP_REGION"
echo "============================================"

# ============================================================
# 1. SCHEDULER JOBS — Knowledge IQ sync service
# ============================================================
if $DEPLOY_SCHEDULER; then
  echo ""
  echo "--- Deploying scheduler (sync service) ---"
  SYNC_DEPLOY="$REPO_ROOT/agents/knowledge-iq/enterpriseGPT/deploy/sync_deploy.sh"
  if [[ -f "$SYNC_DEPLOY" ]]; then
    # sync_deploy.sh uses relative paths anchored to enterpriseGPT/ — must cd there first
    (cd "$REPO_ROOT/agents/knowledge-iq/enterpriseGPT" && bash "$SYNC_DEPLOY")
  else
    echo "  WARNING: $SYNC_DEPLOY not found, skipping."
  fi
fi

# ============================================================
# 2. MCP TOOLS — Cloud Run services for each MCP server
# Prereq: Artifact Registry repo must exist:
#   gcloud artifacts repositories create stratova-mcp \
#     --repository-format=docker --location=us-central1 --project=$GCP_PROJECT
# ============================================================
if $DEPLOY_MCP; then
  echo ""
  echo "--- Deploying MCP tool servers ---"

  # Ensure Artifact Registry repo exists (idempotent)
  if ! gcloud artifacts repositories describe stratova-mcp \
      --location=us-central1 --project="$GCP_PROJECT" &>/dev/null; then
    echo "  Creating Artifact Registry repo 'stratova-mcp'..."
    gcloud artifacts repositories create stratova-mcp \
      --repository-format=docker \
      --location=us-central1 \
      --project="$GCP_PROJECT"
  fi

  deploy_mcp() {
    local dir="$1"
    local label="$2"
    if [[ -f "$dir/deploy.sh" ]]; then
      echo ""
      echo "  → Deploying $label ..."
      (export GCP_PROJECT GOOGLE_CLOUD_PROJECT="$GCP_PROJECT" GCP_REGION GOOGLE_CLOUD_LOCATION="$GCP_REGION"; bash "$dir/deploy.sh")
    else
      echo "  WARNING: $dir/deploy.sh not found, skipping $label."
    fi
  }

  deploy_mcp "$MCP_DIR/rag"            "stratova-rag-mcp"
  deploy_mcp "$MCP_DIR/web"            "stratova-web-scraper-mcp"
  deploy_mcp "$MCP_DIR/google/email"   "stratova-email-mcp"
  deploy_mcp "$MCP_DIR/google/session" "stratova-session-mcp"
  deploy_mcp "$MCP_DIR/google/calendar" "stratova-calendar-mcp"
  deploy_mcp "$MCP_DIR/google/gemini_ds" "stratova-gemini-ds-mcp"

  echo ""
  echo "All MCP servers deployed."
fi

echo ""
echo "Cloud Run deployment complete."
