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

# Build a wheel and install it non-editable so the bundle is fully
# self-contained — `uv sync` installs the project editable, leaving a
# .pth that points back into the repo checkout (app breaks if the repo
# moves, and the bundled daemon would run repo working-tree code).
VENV="${STAGING}/runtime/.venv"
DIST_DIR="$(mktemp -d)"
trap 'rm -rf "$DIST_DIR"' EXIT

uv build --wheel --directory "$REPO_ROOT" --out-dir "$DIST_DIR" >/dev/null
uv export --directory "$REPO_ROOT" --frozen --no-emit-project --no-dev \
  --format requirements.txt -o "$DIST_DIR/requirements.txt" >/dev/null
uv venv --python 3.12 "$VENV" >/dev/null
uv pip install --python "$VENV/bin/python" -r "$DIST_DIR/requirements.txt" >/dev/null
uv pip install --python "$VENV/bin/python" --no-deps "$DIST_DIR"/agentic_os-*.whl >/dev/null

AGENTD="${VENV}/bin/agentd"
if [[ ! -x "$AGENTD" ]]; then
  echo "prepare-desktop-bundle: agentd missing in staged venv: ${AGENTD}" >&2
  exit 1
fi

if grep -rq "$REPO_ROOT/src" "$VENV/lib"/python*/site-packages/*.pth 2>/dev/null; then
  echo "prepare-desktop-bundle: staged venv still references the repo (editable leak)" >&2
  exit 1
fi
if [[ ! -f "$VENV/lib/python3.12/site-packages/agentic_os/api.py" ]]; then
  echo "prepare-desktop-bundle: agentic_os package not materialized in venv" >&2
  exit 1
fi

echo "prepare-desktop-bundle: staged manifest"
find "$STAGING" -type f | sort | sed "s|^${STAGING}/||"

echo "prepare-desktop-bundle: ok"
