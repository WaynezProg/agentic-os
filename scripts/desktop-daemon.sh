#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/desktop-common.sh
source "$SCRIPT_DIR/lib/desktop-common.sh"

ROOT="$(desktop_root)"
API_HOST="${AGENTIC_OS_HOST:-127.0.0.1}"
API_PORT="${AGENTIC_OS_PORT:-8767}"
API_URL="${AGENTIC_OS_API_URL:-http://${API_HOST}:${API_PORT}}"
STATE_DIR="${AGENTIC_OS_STATE_DIR:-${HOME}/.agentic-os}"
if desktop_bundle_mode; then
  REGISTRY="${AGENTIC_OS_REGISTRY:-$ROOT/registry/agents.toml}"
  AGENTD_BIN="$ROOT/runtime/.venv/bin/agentd"
else
  REGISTRY="${AGENTIC_OS_REGISTRY:-$ROOT/examples/agents.toml}"
  AGENTD_BIN=""
fi

PID_FILE="$(desktop_runtime_dir)/daemon.pid"
LOG_FILE="$(desktop_runtime_dir)/daemon.log"

health_check() {
  python3 - "$API_URL/health" <<'PY'
import sys
import urllib.error
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=1) as response:
        sys.exit(0 if response.status == 200 else 1)
except (urllib.error.URLError, TimeoutError):
    sys.exit(1)
PY
}

status_payload() {
  local pid="" managed=false running=false health=down
  pid="$(read_pid "$PID_FILE" || true)"
  if is_running "$pid"; then
    managed=true
    running=true
  elif health_check; then
    running=true
  fi
  if $running && health_check; then
    health=ok
  fi
  RUNNING=$running MANAGED=$managed HEALTH=$health PID="$pid" API_URL="$API_URL" python3 - <<'PY'
import json
import os

running = os.environ["RUNNING"] == "true"
managed = os.environ["MANAGED"] == "true"
pid = os.environ["PID"]
print(
    json.dumps(
        {
            "running": running,
            "managed": managed,
            "pid": int(pid) if pid else None,
            "api_url": os.environ["API_URL"],
            "health": os.environ["HEALTH"],
        }
    )
)
PY
}

cmd_status() {
  status_payload
}

cmd_start() {
  local pid
  pid="$(read_pid "$PID_FILE" || true)"
  if is_running "$pid"; then
    echo "agentd already running (managed pid=${pid})" >&2
    exit 0
  fi
  if health_check; then
    local listener
    listener="$(listener_pid "$API_PORT" || true)"
    if [[ -n "$listener" ]]; then
      write_pid "$PID_FILE" "$listener"
    fi
    echo "agentd already running (external)" >&2
    cmd_status
    exit 0
  fi
  mkdir -p "$STATE_DIR"
  mkdir -p "$(dirname "$LOG_FILE")"
  (
    cd "$ROOT"
    if [[ -n "$AGENTD_BIN" ]]; then
      nohup "$AGENTD_BIN" serve \
        --host "$API_HOST" \
        --port "$API_PORT" \
        --state-dir "$STATE_DIR" \
        --registry "$REGISTRY" >>"$LOG_FILE" 2>&1 &
    else
      nohup uv run agentd serve \
        --host "$API_HOST" \
        --port "$API_PORT" \
        --state-dir "$STATE_DIR" \
        --registry "$REGISTRY" >>"$LOG_FILE" 2>&1 &
    fi
    echo $! >"$PID_FILE"
  )
  for _ in $(seq 1 30); do
    if health_check; then
      local listener
      listener="$(listener_pid "$API_PORT" || true)"
      if [[ -n "$listener" ]]; then
        write_pid "$PID_FILE" "$listener"
      fi
      cmd_status
      exit 0
    fi
    sleep 0.5
  done
  echo "agentd failed to become healthy; see $LOG_FILE" >&2
  exit 1
}

cmd_stop() {
  local pid
  pid="$(read_pid "$PID_FILE" || true)"
  if ! is_running "$pid"; then
    clear_pid "$PID_FILE"
    echo "agentd not managed" >&2
    cmd_status
    exit 0
  fi
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! is_running "$pid"; then
      break
    fi
    sleep 0.25
  done
  if is_running "$pid"; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  clear_pid "$PID_FILE"
  cmd_status
}

cmd_restart() {
  cmd_stop >/dev/null
  cmd_start
}

cmd_reconcile() {
  reconcile_stale_pid "$PID_FILE"
  cmd_status
}

usage() {
  echo "Usage: $0 {start|stop|status|restart|reconcile}" >&2
  exit 1
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  restart) cmd_restart ;;
  reconcile) cmd_reconcile ;;
  *) usage ;;
esac
