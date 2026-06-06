#!/usr/bin/env bash
set -euo pipefail

GATEWAY_URL="${1:?remote_gateway}"
TOKEN="${2:?token}"

BASE="${GATEWAY_URL%/}"
curl -sf -k -H "Authorization: Bearer ${TOKEN}" "${BASE}/health"
curl -sfN -k -H "Authorization: Bearer ${TOKEN}" "${BASE}/events" | head -1

echo "smoke-remote-client: ok"
