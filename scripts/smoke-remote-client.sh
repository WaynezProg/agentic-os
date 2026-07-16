#!/usr/bin/env bash
set -euo pipefail

GATEWAY_URL="${1:?remote_gateway}"
TOKEN="${2:?token}"

BASE="${GATEWAY_URL%/}"
RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$RESPONSE_FILE"' EXIT

request_code() {
  local method="$1"
  local path="$2"
  local expected="$3"
  local body="${4:-}"
  local args=(
    -sS
    -k
    -o "$RESPONSE_FILE"
    -w "%{http_code}"
    -X "$method"
    -H "Authorization: Bearer ${TOKEN}"
  )
  if [[ -n "$body" ]]; then
    args+=(-H "Content-Type: application/json" --data "$body")
  fi
  local actual
  actual="$(curl "${args[@]}" "${BASE}${path}")"
  if [[ "$actual" != "$expected" ]]; then
    echo "${method} ${path}: expected ${expected}, got ${actual}" >&2
    cat "$RESPONSE_FILE" >&2
    exit 1
  fi
}

request_code GET "/health" 200
request_code POST "/fleet/probe" 200
request_code PUT "/workspaces/active" 403 '{"path":"/tmp"}'
request_code PATCH "/health" 405 '{}'
request_code DELETE "/run-templates/smoke-transport" 403
request_code GET "/events/poll?limit=1" 200

first_event_line="$(
  curl -sfN -k --max-time 2 \
    -H "Authorization: Bearer ${TOKEN}" \
    "${BASE}/events" | head -1 || true
)"
if [[ "$first_event_line" != ": connected" ]]; then
  echo "GET /events: missing SSE connected marker" >&2
  exit 1
fi

echo "smoke-remote-client: ok"
