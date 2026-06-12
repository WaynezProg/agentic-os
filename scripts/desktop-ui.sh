#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/desktop-common.sh
source "$SCRIPT_DIR/lib/desktop-common.sh"

ROOT="$(desktop_root)"
UI_HOST="${AGENTIC_OS_UI_HOST:-127.0.0.1}"
UI_PORT="${AGENTIC_OS_UI_PORT:-5173}"
UI_URL="${AGENTIC_OS_UI_URL:-http://${UI_HOST}:${UI_PORT}}"

PID_FILE="$(desktop_runtime_dir)/ui.pid"
LOG_FILE="$(desktop_runtime_dir)/ui.log"
if desktop_bundle_mode; then
  WEB_DIR="$ROOT/web"
else
  WEB_DIR="$ROOT/apps/web"
fi

ui_listening() {
  python3 - "$UI_HOST" "$UI_PORT" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.5)
try:
    sock.connect((host, port))
except OSError:
    sys.exit(1)
else:
    sys.exit(0)
finally:
    sock.close()
PY
}

status_payload() {
  local pid="" managed=false running=false
  pid="$(read_pid "$PID_FILE" || true)"
  if is_running "$pid"; then
    managed=true
    running=true
  elif ui_listening; then
    running=true
  fi
  RUNNING=$running MANAGED=$managed PID="$pid" UI_URL="$UI_URL" python3 - <<'PY'
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
            "ui_url": os.environ["UI_URL"],
        }
    )
)
PY
}

cmd_status() {
  status_payload
}

cmd_start() {
  if desktop_bundle_mode; then
    # Packaged app: the Tauri window serves bundled assets directly
    # (tauri://localhost). A loopback web server here is a useless
    # extra process and an orphan risk on crash — skip it. `stop` and
    # `reconcile` stay live to clean up servers from older versions.
    echo "ui server skipped (bundled assets served by the app)" >&2
    cmd_status
    exit 0
  fi
  local pid
  pid="$(read_pid "$PID_FILE" || true)"
  if is_running "$pid"; then
    echo "ui server already running (managed pid=${pid})" >&2
    cmd_status
    exit 0
  fi
  if ui_listening; then
    local listener
    listener="$(listener_pid "$UI_PORT" || true)"
    if [[ -n "$listener" ]]; then
      write_pid "$PID_FILE" "$listener"
    fi
    echo "ui server already running (external)" >&2
    cmd_status
    exit 0
  fi
  mkdir -p "$(dirname "$LOG_FILE")"
  (
    cd "$ROOT"
    if desktop_bundle_mode; then
      nohup python3 -m http.server "$UI_PORT" \
        --bind "$UI_HOST" \
        --directory "$WEB_DIR" >>"$LOG_FILE" 2>&1 &
    else
      nohup rtk uv run python -m http.server "$UI_PORT" \
        --bind "$UI_HOST" \
        --directory "$WEB_DIR" >>"$LOG_FILE" 2>&1 &
    fi
    echo $! >"$PID_FILE"
  )
  for _ in $(seq 1 20); do
    if ui_listening; then
      local listener
      listener="$(listener_pid "$UI_PORT" || true)"
      if [[ -n "$listener" ]]; then
        write_pid "$PID_FILE" "$listener"
      fi
      cmd_status
      exit 0
    fi
    sleep 0.25
  done
  echo "ui server failed to start; see $LOG_FILE" >&2
  exit 1
}

cmd_stop() {
  local pid
  pid="$(read_pid "$PID_FILE" || true)"
  if ! is_running "$pid"; then
    clear_pid "$PID_FILE"
    echo "ui server not managed" >&2
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
