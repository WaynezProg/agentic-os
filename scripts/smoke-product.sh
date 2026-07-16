#!/usr/bin/env bash
# Behavior-level product smoke for agentic-os (P28b).
# Starts an isolated agentd, exercises launch/config/import/remote/approval flows,
# and writes a text + JSON report. Non-zero exit on first failure cluster.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_ROOT="${SMOKE_PRODUCT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/agentic-os-smoke.XXXXXX")}"
STATE_DIR="$SMOKE_ROOT/state"
REPO_DIR="$SMOKE_ROOT/repo"
HOME_DIR="$SMOKE_ROOT/home"
REGISTRY="$SMOKE_ROOT/agents.toml"
API_HOST="${AGENTIC_OS_HOST:-127.0.0.1}"
API_PORT="${SMOKE_PRODUCT_PORT:-0}"
LOG_FILE="$SMOKE_ROOT/smoke.log"
REPORT_TXT="$SMOKE_ROOT/report.txt"
REPORT_JSON="$SMOKE_ROOT/report.json"
DAEMON_PID=""

declare -a STEP_IDS=()
declare -a STEP_STATUS=()
declare -a STEP_DETAIL=()
FIRST_FAILURE=""

mkdir -p "$STATE_DIR" "$REPO_DIR" "$HOME_DIR"

cleanup() {
  if [[ -n "$DAEMON_PID" ]] && kill -0 "$DAEMON_PID" 2>/dev/null; then
    kill "$DAEMON_PID" 2>/dev/null || true
    wait "$DAEMON_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG_FILE"
}

record_step() {
  local id="$1" status="$2" detail="$3"
  STEP_IDS+=("$id")
  STEP_STATUS+=("$status")
  STEP_DETAIL+=("$detail")
  if [[ "$status" != "pass" && -z "$FIRST_FAILURE" ]]; then
    FIRST_FAILURE="$id"
  fi
  log "[$status] $id — $detail"
}

write_reports() {
  local overall="pass" step_ids_joined step_status_joined step_detail_joined
  if [[ -n "$FIRST_FAILURE" ]]; then
    overall="fail"
  fi
  {
    echo "agentic-os product smoke report"
    echo "overall: $overall"
    echo "log: $LOG_FILE"
    echo "first_failure: ${FIRST_FAILURE:-none}"
    echo
    local i
    for i in "${!STEP_IDS[@]}"; do
      printf '%s\t%s\t%s\n' "${STEP_STATUS[$i]}" "${STEP_IDS[$i]}" "${STEP_DETAIL[$i]}"
    done
  } >"$REPORT_TXT"

  step_ids_joined="$(IFS=' '; printf '%s' "${STEP_IDS[*]-}")"
  step_status_joined="$(IFS=' '; printf '%s' "${STEP_STATUS[*]-}")"
  step_detail_joined="$(IFS='|'; printf '%s' "${STEP_DETAIL[*]-}")"
  ROOT_DIR="$ROOT_DIR" REPORT_JSON="$REPORT_JSON" OVERALL="$overall" FIRST_FAILURE="$FIRST_FAILURE" \
    STEP_IDS="$step_ids_joined" STEP_STATUS="$step_status_joined" \
    STEP_DETAIL_JOINED="$step_detail_joined" \
    LOG_FILE="$LOG_FILE" uv run python - <<'PY'
import json
import os

ids = os.environ.get("STEP_IDS", "").split()
statuses = os.environ.get("STEP_STATUS", "").split()
details = os.environ.get("STEP_DETAIL_JOINED", "").split("|")
steps = []
for idx, step_id in enumerate(ids):
    steps.append(
        {
            "id": step_id,
            "status": statuses[idx] if idx < len(statuses) else "unknown",
            "detail": details[idx] if idx < len(details) else "",
        }
    )
payload = {
    "overall": os.environ["OVERALL"],
    "log_path": os.environ["LOG_FILE"],
    "first_failure": os.environ.get("FIRST_FAILURE") or None,
    "steps": steps,
}
with open(os.environ["REPORT_JSON"], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2)
PY
}

pyjson() {
  python3 -c "$1"
}

api() {
  local method="$1"
  local path="$2"
  shift 2
  curl -sS -X "$method" "${API_BASE}${path}" \
    -H "Content-Type: application/json" \
    "$@"
}

api_code() {
  local method="$1"
  local path="$2"
  shift 2
  curl -sS -o /dev/null -w "%{http_code}" -X "$method" "${API_BASE}${path}" \
    -H "Content-Type: application/json" \
    "$@"
}

wait_for_health() {
  local tries=40
  while ((tries > 0)); do
    if curl -sf "${API_BASE}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
    tries=$((tries - 1))
  done
  return 1
}

write_smoke_registry() {
  cat >"$REGISTRY" <<'TOML'
[[agents]]
id = "shell"
label = "Shell Smoke"
command = ["/usr/bin/printf", "msg=%s model=%s\n", "{{message}}", "{{model}}"]
model_arg = ["--model", "{{model}}"]
cwd_mode = "optional"
stop_policy = "process_group"
health_command = ["/usr/bin/printf", "OK"]
version_command = ["/usr/bin/printf", "1.0.0"]
config_fingerprint_command = ["/usr/bin/printf", "static"]
TOML
}

start_daemon() {
  write_smoke_registry
  if [[ "$API_PORT" == "0" ]]; then
    API_PORT="$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"
  fi
  API_BASE="http://${API_HOST}:${API_PORT}"
  export HOME="$HOME_DIR"
  (
    cd "$ROOT_DIR"
    uv run agentd serve \
      --host "$API_HOST" \
      --port "$API_PORT" \
      --state-dir "$STATE_DIR" \
      --registry "$REGISTRY" >>"$LOG_FILE" 2>&1
  ) &
  DAEMON_PID=$!
  if ! wait_for_health; then
    record_step "daemon_health" "fail" "agentd did not become healthy on ${API_BASE}"
    return 1
  fi
  record_step "daemon_health" "pass" "agentd healthy at ${API_BASE}"
}

step_environment_inventory() {
  local listing detail count kinds
  if ! listing="$(api GET "/environments")"; then
    record_step "environment_inventory" "fail" "environment list request failed"
    return
  fi
  count="$(printf '%s' "$listing" | pyjson 'import json,sys; print(json.load(sys.stdin).get("count", 0))')"
  if ((count < 7)); then
    record_step "environment_inventory" "fail" "expected at least 7 built-in adapters, got ${count}"
    return
  fi
  if ! detail="$(api GET "/environments/claude")"; then
    record_step "environment_inventory" "fail" "Claude environment detail request failed"
    return
  fi
  kinds="$(printf '%s' "$detail" | pyjson '
import json,sys
payload=json.load(sys.stdin)
print(",".join(sorted({surface["kind"] for surface in payload.get("surfaces", [])})))
')"
  if [[ "$kinds" != "capability,cli,config,desktop,ide,runtime" ]]; then
    record_step "environment_inventory" "fail" "Claude surface kinds incomplete: ${kinds}"
    return
  fi
  record_step "environment_inventory" "pass" "${count} adapters; Claude exposes six evidence surfaces"
}

step_verified_change_round_trip() {
  local target before after_preview after_rollback preview change_id preview_status
  local applied apply_status verification_status applied_port rolled_back rollback_status
  local rollback_verified
  target="$REPO_DIR/.agentic-os/config.toml"
  mkdir -p "$(dirname "$target")"
  printf '%s' $'[daemon]\nport = 8767\n' >"$target"
  before="$(cat "$target")"

  preview="$(api POST "/changes/preview" -d "{
    \"operation\": \"config.patch\",
    \"environment_id\": \"agentic_os\",
    \"scope\": \"project\",
    \"cwd\": \"${REPO_DIR}\",
    \"ops\": [{\"op\": \"merge\", \"path\": \"daemon.port\", \"value\": 8768}]
  }")"
  change_id="$(printf '%s' "$preview" | pyjson 'import json,sys; print(json.load(sys.stdin).get("id",""))')"
  preview_status="$(printf '%s' "$preview" | pyjson 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
  after_preview="$(cat "$target")"
  if [[ -z "$change_id" || "$preview_status" != "previewed" || "$before" != "$after_preview" ]]; then
    record_step "verified_change_round_trip" "fail" "preview was not non-mutating (status=${preview_status})"
    return
  fi

  applied="$(api POST "/changes/${change_id}/apply")"
  apply_status="$(printf '%s' "$applied" | pyjson 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
  verification_status="$(printf '%s' "$applied" | pyjson '
import json,sys
verification=json.load(sys.stdin).get("verification") or {}
print(verification.get("status",""))
')"
  applied_port="$(python3 -c 'import sys,tomllib; print(tomllib.loads(open(sys.argv[1], encoding="utf-8").read())["daemon"]["port"])' "$target")"
  if [[ "$apply_status" != "verified" || "$verification_status" != "verified" || "$applied_port" != "8768" ]]; then
    record_step "verified_change_round_trip" "fail" "apply verification failed (status=${apply_status}, verification=${verification_status}, port=${applied_port})"
    return
  fi

  rolled_back="$(api POST "/changes/${change_id}/rollback")"
  rollback_status="$(printf '%s' "$rolled_back" | pyjson 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
  rollback_verified="$(printf '%s' "$rolled_back" | pyjson '
import json,sys
print(str(bool((json.load(sys.stdin).get("rollback") or {}).get("verified"))).lower())
')"
  after_rollback="$(cat "$target")"
  if [[ "$rollback_status" != "rolled_back" || "$rollback_verified" != "true" || "$before" != "$after_rollback" ]]; then
    record_step "verified_change_round_trip" "fail" "rollback did not restore exact bytes (status=${rollback_status})"
    return
  fi
  record_step "verified_change_round_trip" "pass" "preview/apply/verify/rollback restored exact bytes"
}

step_run_model_in_argv() {
  local profile_json session_json session_id argv_line log_line
  profile_json='{"name":"smoke-default","harness_id":"shell","provider":"local","model":"smoke-opus","message_prefix":"","default_env":{}}'
  if ! api POST "/profiles?scope=local&cwd=${REPO_DIR}" -d "$profile_json" >/dev/null; then
    record_step "run_model_in_argv" "fail" "profile create failed"
    return
  fi
  api POST "/projects/${REPO_DIR}/bind-profile" -d '{"run_profile":"smoke-default"}' >/dev/null
  session_json="$(api POST /sessions -d "{\"agent_id\":\"shell\",\"cwd\":\"${REPO_DIR}\",\"message\":\"OK\",\"profile\":\"smoke-default\"}")"
  session_id="$(printf '%s' "$session_json" | pyjson 'import json,sys; print(json.load(sys.stdin)["id"])')"
  argv_line="$(printf '%s' "$session_json" | pyjson 'import json,sys; print(json.dumps(json.load(sys.stdin)["argv"]))')"
  if [[ "$argv_line" != *"smoke-opus"* || "$argv_line" != *"--model"* ]]; then
    record_step "run_model_in_argv" "fail" "argv missing model: ${argv_line}"
    return
  fi
  sleep 0.5
  log_line="$(api GET "/sessions/${session_id}/logs" | pyjson 'import json,sys; d=json.load(sys.stdin); print(d["entries"][0]["line"] if d.get("entries") else "")')"
  if [[ "$log_line" != "msg=OK model=smoke-opus" ]]; then
    record_step "run_model_in_argv" "fail" "stdout mismatch: ${log_line}"
    return
  fi
  record_step "run_model_in_argv" "pass" "argv and stdout include smoke-opus"
}

step_profile_switch_and_rollback() {
  local session_a session_b session_c patch_id
  api POST "/profiles?scope=local&cwd=${REPO_DIR}" \
    -d '{"name":"smoke-default","harness_id":"shell","provider":"local","model":"model-a","message_prefix":"","default_env":{}}' \
    >/dev/null
  session_a="$(api POST /sessions -d "{\"agent_id\":\"shell\",\"cwd\":\"${REPO_DIR}\",\"message\":\"A\",\"profile\":\"smoke-default\"}")"
  if ! printf '%s' "$session_a" | grep -q 'model-a'; then
    record_step "profile_switch" "fail" "first run missing model-a"
    return
  fi
  api POST "/profiles?scope=local&cwd=${REPO_DIR}" \
    -d '{"name":"smoke-default","harness_id":"shell","provider":"local","model":"model-b","message_prefix":"","default_env":{}}' \
    >/dev/null
  session_b="$(api POST /sessions -d "{\"agent_id\":\"shell\",\"cwd\":\"${REPO_DIR}\",\"message\":\"B\",\"profile\":\"smoke-default\"}")"
  if ! printf '%s' "$session_b" | grep -q 'model-b'; then
    record_step "profile_switch" "fail" "switched run missing model-b"
    return
  fi
  patch_id="$(api GET "/patches?harness=agentic_os" | pyjson 'import json,sys; ps=json.load(sys.stdin).get("patches",[]); print(ps[0]["patch_id"] if ps else "")')"
  if [[ -z "$patch_id" ]]; then
    record_step "profile_switch" "fail" "no profile patch to rollback"
    return
  fi
  api POST "/patches/${patch_id}/rollback" -d '{}' >/dev/null
  session_c="$(api POST /sessions -d "{\"agent_id\":\"shell\",\"cwd\":\"${REPO_DIR}\",\"message\":\"C\",\"profile\":\"smoke-default\"}")"
  if ! printf '%s' "$session_c" | grep -q 'model-a'; then
    record_step "profile_switch" "fail" "post-rollback run missing model-a"
    return
  fi
  record_step "profile_switch" "pass" "switch model-b then rollback to model-a"
}

step_catalog_round_trip() {
  local settings="$REPO_DIR/.claude/settings.json" before after patch_id
  mkdir -p "$(dirname "$settings")"
  printf '%s' '{}' >"$settings"
  before="$(cat "$settings")"
  api POST "/catalog/claude/surfaces/patch?cwd=${REPO_DIR}&dry_run=true" \
    -d '{"ops":[{"op":"enable_mcp_server","name":"gh","scope":"project","config":{"command":"npx"}}],"source":"smoke"}' \
    >/dev/null
  patch_id="$(api POST "/catalog/claude/surfaces/patch?cwd=${REPO_DIR}" \
    -d '{"ops":[{"op":"enable_mcp_server","name":"gh","scope":"project","config":{"command":"npx"}}],"source":"smoke"}' \
    | pyjson 'import json,sys; print(json.load(sys.stdin).get("patch_id",""))')"
  if [[ -z "$patch_id" ]]; then
    record_step "catalog_round_trip" "fail" "catalog apply missing patch_id"
    return
  fi
  api POST "/patches/${patch_id}/rollback" -d '{}' >/dev/null
  after="$(cat "$settings")"
  if [[ "$before" != "$after" ]]; then
    record_step "catalog_round_trip" "fail" "settings.json changed after rollback"
    return
  fi
  record_step "catalog_round_trip" "pass" "catalog dry-run/apply/rollback restored bytes"
}

step_harness_config_round_trip() {
  local settings="$REPO_DIR/.claude/settings.json" before after patch_id
  mkdir -p "$(dirname "$settings")"
  printf '%s' '{"model":"x"}' >"$settings"
  before="$(cat "$settings")"
  api POST "/harness-config/claude/patch?cwd=${REPO_DIR}&scope=project&dry_run=true" \
    -d '{"ops":[{"op":"merge","path":"mcpServers.gh","value":{"command":"npx"}}]}' \
    >/dev/null
  patch_id="$(api POST "/harness-config/claude/patch?cwd=${REPO_DIR}&scope=project" \
    -d '{"ops":[{"op":"merge","path":"mcpServers.gh","value":{"command":"npx"}}]}' \
    | pyjson 'import json,sys; print(json.load(sys.stdin).get("patch_id",""))')"
  if [[ -z "$patch_id" ]]; then
    record_step "harness_config_round_trip" "fail" "harness-config apply missing patch_id"
    return
  fi
  api POST "/patches/${patch_id}/rollback" -d '{}' >/dev/null
  after="$(cat "$settings")"
  if [[ "$before" != "$after" ]]; then
    record_step "harness_config_round_trip" "fail" "harness settings changed after rollback"
    return
  fi
  record_step "harness_config_round_trip" "pass" "harness-config dry-run/apply/rollback restored bytes"
}

step_registry_round_trip() {
  local before after patch_id
  before="$(cat "$REGISTRY")"
  patch_id="$(api POST /registry/agents -d '{"id":"smoke-demo","label":"Smoke Demo","command":["/usr/bin/printf","{{message}}"],"cwd_mode":"optional","health_command":["/usr/bin/printf","OK"],"version_command":["/usr/bin/printf","1.0.0"],"config_fingerprint_command":["/usr/bin/printf","static"],"config_path":"~/.smoke-demo","default_provider":"demo","enabled":true}' | pyjson 'import json,sys; print(json.load(sys.stdin).get("patch_id",""))')"
  if [[ -z "$patch_id" ]]; then
    record_step "registry_round_trip" "fail" "registry apply missing patch_id"
    return
  fi
  api POST "/patches/${patch_id}/rollback" -d '{}' >/dev/null
  after="$(cat "$REGISTRY")"
  if [[ "$before" != "$after" ]]; then
    record_step "registry_round_trip" "fail" "agents.toml changed after rollback"
    return
  fi
  record_step "registry_round_trip" "pass" "registry apply/rollback restored bytes"
}

step_import_export_noop() {
  local export_a export_b
  api POST /skills/smoke-skill -d '{"label":"Smoke Skill"}' >/dev/null
  export_a="$(api GET "/setup/export?cwd=${REPO_DIR}")"
  if printf '%s' "$export_a" | grep -q 'super-secret'; then
    record_step "import_export_noop" "fail" "export leaked secret literal"
    return
  fi
  api POST "/setup/import?cwd=${REPO_DIR}&dry_run=false" -d "$export_a" >/dev/null
  export_b="$(api GET "/setup/export?cwd=${REPO_DIR}")"
  if ! DIFF_DETAIL="$(printf '%s\n%s' "$export_a" "$export_b" | pyjson '
import json,sys
lines=[l for l in sys.stdin.read().splitlines() if l.strip()]
a=json.loads(lines[0]); b=json.loads(lines[1])
for bundle in (a,b):
    bundle.pop("exported_at", None)
if a!=b:
    print("export bundles differ after re-import")
')"; then
    record_step "import_export_noop" "fail" "${DIFF_DETAIL:-export bundles differ}"
    return
  fi
  record_step "import_export_noop" "pass" "export re-import is a no-op"
}

step_remote_enforcement() {
  local remote_code local_code
  remote_code="$(api_code POST /remote/pairing/start -H 'X-Agentic-OS-Gateway: 1' -d '{}')"
  local_code="$(api_code POST /remote/pairing/start -d '{}')"
  if [[ "$remote_code" != "403" || "$local_code" != "200" ]]; then
    record_step "remote_enforcement" "fail" "gateway=${remote_code} localhost=${local_code}"
    return
  fi
  record_step "remote_enforcement" "pass" "localhost-only route rejects gateway client"
}

step_approval_loop() {
  local blocked approval_id approved_session_id approved_status log_line
  api POST /policy/shell -d "{
    \"enabled\": true,
    \"readonly\": false,
    \"allowed_skill_ids\": [\"*\"],
    \"allowed_mcp_server_ids\": [\"*\"],
    \"allowed_tool_names\": [\"*\"],
    \"approval_required_tool_names\": [\"session.start\"],
    \"allowed_model_ids\": [\"*\"],
    \"cwd_roots\": [\"${REPO_DIR}\"],
    \"rate_limit_per_minute\": 60
  }" >/dev/null
  blocked="$(api POST /sessions -d "{\"agent_id\":\"shell\",\"cwd\":\"${REPO_DIR}\",\"message\":\"approve-me\"}")"
  approval_id="$(printf '%s' "$blocked" | pyjson 'import json,sys; print(json.load(sys.stdin).get("approval_id",""))' 2>/dev/null || true)"
  if [[ -z "$approval_id" ]]; then
    record_step "approval_loop" "fail" "expected approval_required session"
    return
  fi
  local approved_json
  approved_json="$(api POST "/approvals/${approval_id}/approve" -d '{}')"
  approved_status="$(printf '%s' "$approved_json" | pyjson 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
  approved_session_id="$(printf '%s' "$approved_json" | pyjson 'import json,sys; print(json.load(sys.stdin).get("approved_session_id",""))')"
  if [[ "$approved_status" != "approved" ]]; then
    record_step "approval_loop" "fail" "approve did not return approved (status=${approved_status})"
    return
  fi
  if [[ -z "$approved_session_id" ]]; then
    record_step "approval_loop" "fail" "approved session not linked"
    return
  fi
  log_line="$(api GET "/sessions/${approved_session_id}/logs" | pyjson 'import json,sys; d=json.load(sys.stdin); print(d["entries"][0]["line"] if d.get("entries") else "")')"
  if [[ "$log_line" != *"approve-me"* ]]; then
    record_step "approval_loop" "fail" "approved run stdout mismatch: ${log_line}"
    return
  fi
  record_step "approval_loop" "pass" "approval launched linked session ${approved_session_id}"
}

main() {
  : >"$LOG_FILE"
  log "smoke root: $SMOKE_ROOT"
  start_daemon || true
  if [[ -z "$FIRST_FAILURE" ]]; then step_environment_inventory; fi
  if [[ -z "$FIRST_FAILURE" ]]; then step_verified_change_round_trip; fi
  if [[ -z "$FIRST_FAILURE" ]]; then step_run_model_in_argv; fi
  if [[ -z "$FIRST_FAILURE" ]]; then step_profile_switch_and_rollback; fi
  if [[ -z "$FIRST_FAILURE" ]]; then step_catalog_round_trip; fi
  if [[ -z "$FIRST_FAILURE" ]]; then step_harness_config_round_trip; fi
  if [[ -z "$FIRST_FAILURE" ]]; then step_registry_round_trip; fi
  if [[ -z "$FIRST_FAILURE" ]]; then step_import_export_noop; fi
  if [[ -z "$FIRST_FAILURE" ]]; then step_remote_enforcement; fi
  if [[ -z "$FIRST_FAILURE" ]]; then step_approval_loop; fi
  write_reports
  cat "$REPORT_TXT"
  echo "JSON report: $REPORT_JSON"
  if [[ -n "$FIRST_FAILURE" ]]; then
    echo "manual follow-up: inspect $LOG_FILE and fix step ${FIRST_FAILURE}" >&2
    exit 1
  fi
}

main "$@"
