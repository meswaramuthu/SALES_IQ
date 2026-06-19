#!/usr/bin/env bash
# Central entry point: deploy all Cloud Run services.
# Covers:
#   1. Scheduler jobs  — Knowledge IQ sync service (Cloud Run Job + Webhook Service)
#   2. MCP tools       — placeholder for future MCP tool servers as Cloud Run services
#
# Usage:
#   ./deployment/deploy_cloudrun.sh [--scheduler] [--mcp]
#   (no flags = deploy everything)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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
export ARTIFACT_REGISTRY_REPO="${ARTIFACT_REGISTRY_REPO:-}"

if [[ -z "$GCP_PROJECT" || -z "$GCS_BUCKET" ]]; then
  echo "ERROR: GCP_PROJECT and GCS_BUCKET must be set."
  exit 1
fi

# ============================================================
# 1. SCHEDULER JOBS — Knowledge IQ sync service
# ============================================================
if $DEPLOY_SCHEDULER; then
  echo ""
  echo "--- Deploying scheduler (sync service) ---"
  SYNC_DEPLOY="$REPO_ROOT/agents/knowledge-iq/enterpriseGPT/deploy/sync_deploy.sh"
  if [[ -f "$SYNC_DEPLOY" ]]; then
    bash "$SYNC_DEPLOY"
  else
    echo "WARNING: $SYNC_DEPLOY not found, skipping."
  fi
fi

# ============================================================
# 2. MCP TOOLS — Cloud Run services for each MCP tool server
# ============================================================
if $DEPLOY_MCP; then
  echo ""
  echo "--- Deploying MCP tool servers ---"
  # TODO: Add MCP tool deployments here as they are created.
  # Example pattern:
  #   gcloud run deploy my-mcp-tool \
  #     --image "$ARTIFACT_REGISTRY_REPO/my-mcp-tool:latest" \
  #     --region "$GCP_REGION" \
  #     --project "$GCP_PROJECT" \
  #     --no-allow-unauthenticated
  echo "  (no MCP tools registered yet — add entries above when tools are created)"
fi

echo ""
echo "Cloud Run deployment complete."
