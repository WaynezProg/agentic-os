#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

API_HOST="${AGENTIC_OS_HOST:-127.0.0.1}"
API_PORT="${AGENTIC_OS_PORT:-8767}"
UI_HOST="${AGENTIC_OS_UI_HOST:-127.0.0.1}"
UI_PORT="${AGENTIC_OS_UI_PORT:-5173}"
STATE_DIR="${AGENTIC_OS_STATE_DIR:-$ROOT_DIR/.agentic-os}"
REGISTRY="${AGENTIC_OS_REGISTRY:-$ROOT_DIR/examples/agents.toml}"

PIDS=()

cleanup() {
  local pid
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

cd "$ROOT_DIR"

echo "Starting agentd on http://$API_HOST:$API_PORT"
rtk uv run agentd serve \
  --host "$API_HOST" \
  --port "$API_PORT" \
  --state-dir "$STATE_DIR" \
  --registry "$REGISTRY" &
PIDS+=("$!")

echo "Starting web UI on http://$UI_HOST:$UI_PORT"
rtk uv run python -m http.server "$UI_PORT" \
  --bind "$UI_HOST" \
  --directory "$ROOT_DIR/apps/web" &
PIDS+=("$!")

echo
echo "Open http://$UI_HOST:$UI_PORT"
echo "Daemon API: http://$API_HOST:$API_PORT"
echo "Press Ctrl-C to stop both servers."

while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid"
      exit $?
    fi
  done
  sleep 1
done
