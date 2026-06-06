#!/usr/bin/env bash
# Stage agentic-os runtime resources for Tauri macOS bundle (P11.5).
# Assembles only — never starts daemon or UI processes.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGING="${REPO_ROOT}/apps/desktop/src-tauri/bundle-resources/agentic-os"

echo "prepare-desktop-bundle: staging → ${STAGING}"

rm -rf "$STAGING"
mkdir -p "$STAGING/scripts/lib" "$STAGING/web" "$STAGING/registry" "$STAGING/runtime"

cp "$REPO_ROOT/scripts/desktop-daemon.sh" "$STAGING/scripts/"
cp "$REPO_ROOT/scripts/desktop-ui.sh" "$STAGING/scripts/"
cp "$REPO_ROOT/scripts/lib/desktop-common.sh" "$STAGING/scripts/lib/"
cp -R "$REPO_ROOT/apps/web/." "$STAGING/web/"
cp "$REPO_ROOT/examples/agents.toml" "$STAGING/registry/agents.toml"

if ! command -v uv >/dev/null 2>&1; then
  echo "prepare-desktop-bundle: uv is required on the build machine" >&2
  exit 1
fi

UV_PROJECT_ENVIRONMENT="${STAGING}/runtime/.venv" uv sync \
  --directory "$REPO_ROOT" \
  --python 3.12 \
  --frozen

AGENTD="${STAGING}/runtime/.venv/bin/agentd"
if [[ ! -x "$AGENTD" ]]; then
  echo "prepare-desktop-bundle: agentd missing in staged venv: ${AGENTD}" >&2
  exit 1
fi

echo "prepare-desktop-bundle: staged manifest"
find "$STAGING" -type f | sort | sed "s|^${STAGING}/||"

echo "prepare-desktop-bundle: ok"
