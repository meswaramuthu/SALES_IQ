#!/usr/bin/env bash
# Creates an agent inside a Gemini Enterprise app (Vertex AI Agent Builder).
# Usage:
#   ./create_gemini_enterprise_agent.sh \
#       <PROJECT_ID> \
#       <ENGINE_ID> \
#       <AGENT_NAME> \
#       <DESCRIPTION> \
#       [REASONING_ENGINE_RESOURCE]
#
# REASONING_ENGINE_RESOURCE (optional):
#   Full resource path of a Vertex AI Reasoning Engine, e.g.:
#   projects/123456/locations/us-central1/reasoningEngines/456789
#
# Examples:
#   # Without reasoning engine
#   ./create_gemini_enterprise_agent.sh \
#       light-lacing-497510-b1 \
#       gemini-enterprise-app_1781176722287 \
#       "My Agent" \
#       "This agent does X"
#
#   # With reasoning engine
#   ./create_gemini_enterprise_agent.sh \
#       light-lacing-497510-b1 \
#       gemini-enterprise-app_1781176722287 \
#       "My Agent" \
#       "This agent does X" \
#       "projects/528271267622/locations/us-central1/reasoningEngines/2775842998401892352"

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT_ID="${1:?Usage: $0 <PROJECT_ID> <ENGINE_ID> <AGENT_NAME> <DESCRIPTION> [REASONING_ENGINE]}"
ENGINE_ID="${2:?Missing ENGINE_ID}"
AGENT_NAME="${3:?Missing AGENT_NAME}"
DESCRIPTION="${4:?Missing DESCRIPTION}"
REASONING_ENGINE="${5:-}"
COLLECTION="default_collection"
ASSISTANT="default_assistant"
LOCATION="global"

BASE_URL="https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_ID}/locations/${LOCATION}/collections/${COLLECTION}/engines/${ENGINE_ID}/assistants/${ASSISTANT}/agents"

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

info "Project         : $PROJECT_ID"
info "Engine ID       : $ENGINE_ID"
info "Agent name      : $AGENT_NAME"
info "Description     : $DESCRIPTION"
info "Reasoning engine: ${REASONING_ENGINE:-none}"

ACCESS_TOKEN="$(gcloud auth print-access-token 2>/dev/null)" \
  || error "No active gcloud credentials. Run: gcloud auth login --update-adc"

# ── Build request body ────────────────────────────────────────────────────────
if [[ -n "$REASONING_ENGINE" ]]; then
  ADK_DEFINITION='{
    "toolSettings": {},
    "provisionedReasoningEngine": {
      "reasoningEngine": "'"$REASONING_ENGINE"'"
    }
  }'
else
  ADK_DEFINITION='{
    "toolSettings": {}
  }'
fi

REQUEST_BODY='{
  "displayName": "'"$AGENT_NAME"'",
  "description": "'"$DESCRIPTION"'",
  "adkAgentDefinition": '"$ADK_DEFINITION"',
  "sharingConfig": {
    "scope": "ALL_USERS"
  },
  "agentInvocationSpec": {
    "invocationMode": "AUTOMATIC"
  }
}'

# ── Create agent ──────────────────────────────────────────────────────────────
info "Creating agent '$AGENT_NAME'…"

http_request \
  -X POST \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-goog-user-project: $PROJECT_ID" \
  "$BASE_URL" \
  -d "$REQUEST_BODY"

if [[ "$RESP_HTTP" == "200" ]]; then
  AGENT_ID=$(echo "$RESP_BODY" | jq -r '.name' | awk -F'/' '{print $NF}')
  info "Agent created successfully. ID: $AGENT_ID"
  echo ""
  echo "$RESP_BODY" | jq '{name, displayName, description, state}'
elif [[ "$RESP_HTTP" == "409" ]]; then
  info "Agent already exists."
else
  error "Agent creation failed (HTTP $RESP_HTTP): $RESP_BODY"
fi

# ── Console link ──────────────────────────────────────────────────────────────
echo ""
echo "View in console:"
echo "  https://console.cloud.google.com/gen-app-builder/engines/${ENGINE_ID}/assistants/default_assistant/agents?project=${PROJECT_ID}"
