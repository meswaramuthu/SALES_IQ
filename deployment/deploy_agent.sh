#!/usr/bin/env bash
# Central entry point: deploy the full Knowledge IQ / enterpriseGPT agent stack.
# Triggers: Agent Engine deployment, Vertex AI RAG corpus, GCS config + prompt upload,
#           and Gemini Enterprise connector registration.
#
# Usage:
#   ./deployment/deploy_agent.sh
#
# Required env vars (set here or export before running):
#   GCP_PROJECT      — Google Cloud project ID
#   GCP_REGION       — Region for Agent Engine (default: us-central1)
#   GCS_BUCKET       — GCS bucket for config + state storage

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

AGENT_DEPLOY_DIR="$REPO_ROOT/agents/knowledge-iq/enterpriseGPT/deploy"

# --- Configuration ---
export GCP_PROJECT="${GCP_PROJECT:-}"
export GCP_REGION="${GCP_REGION:-us-central1}"
export GCS_BUCKET="${GCS_BUCKET:-}"

if [[ -z "$GCP_PROJECT" || -z "$GCS_BUCKET" ]]; then
  echo "ERROR: GCP_PROJECT and GCS_BUCKET must be set."
  echo "  export GCP_PROJECT=your-project-id"
  echo "  export GCS_BUCKET=your-bucket-name"
  exit 1
fi

echo "============================================"
echo " Deploying Knowledge IQ / enterpriseGPT"
echo " Project : $GCP_PROJECT"
echo " Region  : $GCP_REGION"
echo " Bucket  : $GCS_BUCKET"
echo "============================================"

# Run the full deployment orchestrator
cd "$REPO_ROOT/agents/knowledge-iq/enterpriseGPT"
python "$AGENT_DEPLOY_DIR/deploy_full.py"

echo ""
echo "Agent deployment complete."
