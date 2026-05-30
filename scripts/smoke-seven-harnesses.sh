#!/usr/bin/env bash
# Manual smoke: launch one Harness Run per non-shell harness instance.
# Exit 0 when each run creates a session record (upstream CLI failures are OK).
set -euo pipefail

API="${AGENTIC_OS_API:-http://127.0.0.1:8767}"
CWD="${AGENTIC_OS_CWD:-$(pwd)}"
MESSAGE="${AGENTIC_OS_MESSAGE:-OK}"

for id in claude codex opencode qwen openclaw hermes cursor; do
  echo "==> run ${id}"
  uv run agentctl run "${id}" --api "${API}" --cwd "${CWD}" --message "${MESSAGE}" || true
done

echo "done (check agentctl sessions list)"
