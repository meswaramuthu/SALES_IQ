#!/usr/bin/env bash
# Manages a Gemini Enterprise app via Vertex AI Agent Builder.
# Usage:
#   ./create_gemini_enterprise_app.sh [PROJECT_ID] [APP_NAME] [LOCATION]
#   ./create_gemini_enterprise_app.sh [PROJECT_ID] [APP_NAME] [LOCATION] --delete

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT_ID="${1:-ninth-archway-496404-s2}"
APP_NAME="${2:-stratova-gemini}"
LOCATION="${3:-global}"
ACTION="${4:-create}"
COLLECTION="default_collection"
ENGINE_URL="https://discoveryengine.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION}/collections/${COLLECTION}/engines"

# ── Helpers ───────────────────────────────────────────────────────────────────
info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

require() {
  command -v "$1" &>/dev/null || error "'$1' is not installed or not in PATH."
}

http_request() {
  local tmp; tmp=$(mktemp)
  RESP_HTTP=$(curl -s -o "$tmp" -w "%{http_code}" "$@")
  RESP_BODY=$(cat "$tmp")
  rm -f "$tmp"
}

# ── Pre-flight ────────────────────────────────────────────────────────────────
require gcloud
require curl
require jq

info "Project  : $PROJECT_ID"
info "App name : $APP_NAME"
info "Location : $LOCATION"
info "Action   : $ACTION"

ACCESS_TOKEN="$(gcloud auth print-access-token 2>/dev/null)" \
  || error "No active gcloud credentials. Run: gcloud auth login --update-adc"

AUTH_HEADERS=(
  -H "Authorization: Bearer $ACCESS_TOKEN"
  -H "Content-Type: application/json"
  -H "x-goog-user-project: $PROJECT_ID"
)

# ── Delete ────────────────────────────────────────────────────────────────────
if [[ "$ACTION" == "--delete" ]]; then
  info "Deleting app '$APP_NAME'…"
  http_request -X DELETE "${AUTH_HEADERS[@]}" "${ENGINE_URL}/${APP_NAME}"

  if [[ "$RESP_HTTP" == "200" || "$RESP_HTTP" == "204" ]]; then
    info "App '$APP_NAME' deleted successfully."
  elif [[ "$RESP_HTTP" == "404" ]]; then
    info "App '$APP_NAME' not found — nothing to delete."
  else
    error "Delete failed (HTTP $RESP_HTTP): $RESP_BODY"
  fi
  exit 0
fi

# ── Create ────────────────────────────────────────────────────────────────────
info "Enabling required APIs…"
gcloud services enable \
  discoveryengine.googleapis.com \
  aiplatform.googleapis.com \
  --project="$PROJECT_ID"

info "Creating Gemini Enterprise app '$APP_NAME'…"

http_request \
  -X POST "${AUTH_HEADERS[@]}" \
  "${ENGINE_URL}?engineId=${APP_NAME}" \
  -d '{
    "displayName": "'"$APP_NAME"'",
    "solutionType": "SOLUTION_TYPE_SEARCH",
    "industryVertical": "GENERIC",
    "appType": "APP_TYPE_INTRANET",
    "searchEngineConfig": {
      "searchTier": "SEARCH_TIER_ENTERPRISE",
      "searchAddOns": ["SEARCH_ADD_ON_LLM"]
    },
    "knowledgeGraphConfig": {
      "enablePrivateKnowledgeGraph": true
    }
  }'

if [[ "$RESP_HTTP" == "200" ]]; then
  APP_OP=$(echo "$RESP_BODY" | jq -r '.name // "check console"')
  info "App created. Operation: $APP_OP"
elif [[ "$RESP_HTTP" == "409" ]]; then
  info "App '$APP_NAME' already exists."
else
  error "App creation failed (HTTP $RESP_HTTP): $RESP_BODY"
fi

info "Done."
echo ""
echo "View in console:"
echo "  https://console.cloud.google.com/gen-app-builder/apps?project=${PROJECT_ID}"
