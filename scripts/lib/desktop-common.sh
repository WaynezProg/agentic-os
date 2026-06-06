#!/usr/bin/env bash
# Shared helpers for desktop lifecycle scripts.

set -euo pipefail

desktop_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

desktop_state_dir() {
  echo "${AGENTIC_OS_STATE_DIR:-$(desktop_root)/.agentic-os}"
}

desktop_runtime_dir() {
  local dir
  dir="$(desktop_state_dir)/desktop"
  mkdir -p "$dir"
  echo "$dir"
}

read_pid() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    cat "$pid_file"
  fi
}

write_pid() {
  echo "$2" >"$1"
}

clear_pid() {
  rm -f "$1"
}

is_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

emit_json() {
  python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)))' <<<"$1"
}
