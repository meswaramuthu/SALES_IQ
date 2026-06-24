#!/usr/bin/env bash
# Agent deployment dispatcher.
#
# ADDING A NEW AGENT
# ──────────────────
# Add one line to AGENT_REGISTRY below:
#   "slug|group|path/from/repo-root|Display Name"
#
# The agent directory must contain one of:
#   deploy/deploy_full.py   → invoked with: uv run --env-file .env python deploy/deploy_full.py \
#                                              --project GCP_PROJECT --location GCP_REGION --bucket GCS_BUCKET
#   deploy/deploy.sh        → invoked with: bash deploy/deploy.sh (fallback)
#
# USAGE
# ──────────────────
#   ./deployment/deploy_agent.sh                     # deploy all agents
#   ./deployment/deploy_agent.sh --agent knowledge-iq
#   ./deployment/deploy_agent.sh --group knowledge-iq
#   ./deployment/deploy_agent.sh --list
#
# REQUIRED ENV VARS
#   GCP_PROJECT   — GCP project ID
#   GCP_REGION    — region (default: us-central1)
#   GCS_BUCKET    — GCS staging/config bucket

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ─────────────────────────────────────────────────────────────────────────────
# AGENT REGISTRY
# Format:  "slug|group|path-from-repo-root|Display Name"
#
# slug   : unique identifier used with --agent flag
# group  : folder name under agents/ — used with --group flag
# path   : directory that contains the deploy/ subfolder (relative to REPO_ROOT)
# name   : human-readable label shown in logs
# ─────────────────────────────────────────────────────────────────────────────
AGENT_REGISTRY=(
  # Format: "slug|group|path-from-repo-root|Display Name"
  # slug  — used with --agent flag  (convention: group/agent-folder)
  # group — used with --group flag  (top-level folder under agents/)
  "knowledge-iq/enterpriseGPT|knowledge-iq|agents/knowledge-iq/enterpriseGPT|KnowledgeIQ — Data Gateway (Laabu)"
  # Add new agents below — one line each:
  # "knowledge-iq/adminGPT|knowledge-iq|agents/knowledge-iq/adminGPT|Admin IQ — Platform Administrator"
  # "sales-iq/aura|sales-iq|agents/sales-iq/aura|SalesIQ — AURA (Laabu)"
  # "support-iq/jany|support-iq|agents/support-iq/jany|SupportIQ — JANY (Laabu)"
  # "sub-agents/crm|sub-agents|agents/sub-agents/crm|Laabu CRM Agent — HubSpot"
)

# ─────────────────────────────────────────────────────────────────────────────
# CLI args
# ─────────────────────────────────────────────────────────────────────────────
TARGET_AGENT=""    # --agent SLUG
TARGET_GROUP=""    # --group GROUP
DEPLOY_ALL=true
LIST_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)  TARGET_AGENT="$2"; DEPLOY_ALL=false; shift 2 ;;
    --group)  TARGET_GROUP="$2"; DEPLOY_ALL=false; shift 2 ;;
    --all)    DEPLOY_ALL=true; shift ;;
    --list)   LIST_ONLY=true; shift ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

# ─────────────────────────────────────────────────────────────────────────────
# --list: print registry and exit
# ─────────────────────────────────────────────────────────────────────────────
if $LIST_ONLY; then
  echo "Available agents:"
  echo ""
  printf "  %-36s %-16s %s\n" "SLUG" "GROUP" "NAME"
  printf "  %-36s %-16s %s\n" "----" "-----" "----"
  for entry in "${AGENT_REGISTRY[@]}"; do
    IFS='|' read -r slug group _path name <<< "$entry"
    printf "  %-36s %-16s %s\n" "$slug" "$group" "$name"
  done
  echo ""
  echo "Usage:"
  echo "  Deploy one agent:   $0 --agent knowledge-iq/enterpriseGPT"
  echo "  Deploy a group:     $0 --group knowledge-iq"
  echo "  Deploy everything:  $0 --all"
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# Env var validation
# ─────────────────────────────────────────────────────────────────────────────
export GCP_PROJECT="${GCP_PROJECT:-}"
export GCP_REGION="${GCP_REGION:-us-central1}"
export GCS_BUCKET="${GCS_BUCKET:-}"

if [[ -z "$GCP_PROJECT" || -z "$GCS_BUCKET" ]]; then
  echo "ERROR: GCP_PROJECT and GCS_BUCKET must be set."
  echo "  export GCP_PROJECT=your-project-id"
  echo "  export GCS_BUCKET=your-bucket-name"
  exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# Deploy dispatcher: run one agent's deploy script
# ─────────────────────────────────────────────────────────────────────────────
_deploy_agent() {
  local slug="$1"
  local name="$2"
  local agent_dir="$3"   # absolute path

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Deploying: $name"
  echo "  Slug:      $slug"
  echo "  Dir:       $agent_dir"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  if [[ ! -d "$agent_dir" ]]; then
    echo "  ERROR: directory not found: $agent_dir"
    return 1
  fi

  cd "$agent_dir"

  if [[ -f "deploy/deploy_full.py" ]]; then
    # Preferred: full Python orchestrator
    uv run --env-file .env python "deploy/deploy_full.py" \
      --project "$GCP_PROJECT" \
      --location "$GCP_REGION" \
      --bucket "$GCS_BUCKET" \
      --skip-gemini-enterprise || return 1

  elif [[ -f "deploy/deploy.sh" ]]; then
    # Fallback: bash deploy script
    bash "deploy/deploy.sh" || return 1

  else
    echo "  ERROR: no deploy script found in $agent_dir/deploy/"
    echo "  Expected: deploy/deploy_full.py  or  deploy/deploy.sh"
    return 1
  fi

  echo "  ✓ $name — done."
  cd "$REPO_ROOT"
}

# ─────────────────────────────────────────────────────────────────────────────
# Build the deploy list based on flags
# ─────────────────────────────────────────────────────────────────────────────
declare -a TO_DEPLOY=()   # elements: "slug|name|abs-path"

for entry in "${AGENT_REGISTRY[@]}"; do
  IFS='|' read -r slug group rel_path name <<< "$entry"
  abs_path="$REPO_ROOT/$rel_path"

  if $DEPLOY_ALL; then
    TO_DEPLOY+=("$slug|$name|$abs_path")
  elif [[ -n "$TARGET_AGENT" && "$slug" == "$TARGET_AGENT" ]]; then
    TO_DEPLOY+=("$slug|$name|$abs_path")
  elif [[ -n "$TARGET_GROUP" && "$group" == "$TARGET_GROUP" ]]; then
    TO_DEPLOY+=("$slug|$name|$abs_path")
  fi
done

if [[ ${#TO_DEPLOY[@]} -eq 0 ]]; then
  if [[ -n "$TARGET_AGENT" ]]; then
    echo "ERROR: no agent with slug '$TARGET_AGENT' found in registry."
  elif [[ -n "$TARGET_GROUP" ]]; then
    echo "ERROR: no agents in group '$TARGET_GROUP' found in registry."
  else
    echo "ERROR: registry is empty."
  fi
  echo "Run '$0 --list' to see available agents."
  exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# Run deploys
# ─────────────────────────────────────────────────────────────────────────────
echo "============================================"
echo " Agent Deployment"
echo " Project  : $GCP_PROJECT"
echo " Region   : $GCP_REGION"
echo " Bucket   : $GCS_BUCKET"
echo " Agents   : ${#TO_DEPLOY[@]}"
echo "============================================"

FAILED=()

for item in "${TO_DEPLOY[@]}"; do
  IFS='|' read -r slug name abs_path <<< "$item"
  if ! _deploy_agent "$slug" "$name" "$abs_path"; then
    FAILED+=("$slug")
  fi
done

echo ""
echo "============================================"
if [[ ${#FAILED[@]} -eq 0 ]]; then
  echo " All agents deployed successfully."
else
  echo " Completed with errors."
  echo " Failed: ${FAILED[*]}"
  exit 1
fi
echo "============================================"
