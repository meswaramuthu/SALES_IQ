#!/usr/bin/env bash
# Shared helper: idempotently save a value to GCP Secret Manager.
# Source this file, then call save_secret NAME VALUE [PROJECT_ID]
#
# Usage:
#   source "$(dirname "${BASH_SOURCE[0]}")/secret_utils.sh"
#   save_secret "laabu-knowledge-iq-engine-id" "$RESOURCE_NAME" "$GCP_PROJECT"
#
# Secret naming convention:
#   Agent engines:   laabu-agents-{slug}-engine-id   e.g. laabu-agents-knowledge-iq-engine-id
#   MCP server URLs: laabu-mcp-{service}-url          e.g. laabu-mcp-rag-url

save_secret() {
  local secret_name="$1"
  local secret_value="$2"
  local project="${3:-${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}}"

  if [[ -z "$project" ]]; then
    echo "ERROR save_secret: no project — set GCP_PROJECT or pass as third arg" >&2
    return 1
  fi
  if [[ -z "$secret_value" ]]; then
    echo "WARNING save_secret: empty value for '$secret_name' — skipping" >&2
    return 0
  fi

  if gcloud secrets describe "$secret_name" --project "$project" &>/dev/null; then
    printf '%s' "$secret_value" | gcloud secrets versions add "$secret_name" \
      --data-file=- --project "$project"
    echo "  [Secret Manager] Updated '$secret_name'."
  else
    printf '%s' "$secret_value" | gcloud secrets create "$secret_name" \
      --data-file=- \
      --replication-policy="automatic" \
      --project "$project"
    echo "  [Secret Manager] Created '$secret_name'."
  fi
}
