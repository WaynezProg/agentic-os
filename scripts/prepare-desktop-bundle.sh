#!/usr/bin/env bash
# Stage agentic-os runtime resources for Tauri macOS bundle (P11.5).
# Assembles only — never starts daemon or UI processes.

set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "prepare-desktop-bundle: macOS only (stages a relocatable darwin runtime)" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGING="${REPO_ROOT}/apps/desktop/src-tauri/bundle-resources/agentic-os"
PYTHON_BUILD="cpython-3.12-macos-aarch64-none"

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

# Ship a full relocatable CPython (python-build-standalone) inside the
# bundle and install the project wheel straight into its site-packages.
# venvs are NOT relocatable: console-script shebangs and pyvenv.cfg pin
# build-time absolute paths, and resource copiers (tauri/ditto) turn
# the bin/python symlink into a real file whose @rpath libpython lookup
# then misses. A standalone CPython resolves everything relative to its
# own binary, so the copied app needs nothing from the build machine.
uv python install "$PYTHON_BUILD" >/dev/null 2>&1 || true
PY_SOURCE="$(uv python find --managed-python --no-project --resolve-links "$PYTHON_BUILD")"
PY_INSTALL="$(cd "$(dirname "$PY_SOURCE")/.." && pwd)"
cp -R "$PY_INSTALL/." "$STAGING/runtime/python/"
BUNDLED_PY="$STAGING/runtime/python/bin/python3.12"
BUNDLED_LIB="$STAGING/runtime/python/lib/libpython3.12.dylib"
# This copy is ours to mutate; drop uv's PEP 668 guard so packages can
# be installed straight into its site-packages.
rm -f "$STAGING/runtime/python/lib/python3.12/EXTERNALLY-MANAGED"

if [[ ! -f "$BUNDLED_PY" || -L "$BUNDLED_PY" || ! -f "$BUNDLED_LIB" ]]; then
  echo "prepare-desktop-bundle: managed Python runtime is incomplete" >&2
  exit 1
fi
while IFS= read -r link; do
  if [[ "$(readlink "$link")" == /* ]]; then
    echo "prepare-desktop-bundle: absolute runtime symlink: $link" >&2
    exit 1
  fi
done < <(find "$STAGING/runtime/python" -type l)

DIST_DIR="$(mktemp -d)"
trap 'rm -rf "$DIST_DIR"' EXIT

uv build --wheel --directory "$REPO_ROOT" --out-dir "$DIST_DIR" >/dev/null
uv export --directory "$REPO_ROOT" --frozen --no-emit-project --no-dev \
  --format requirements.txt -o "$DIST_DIR/requirements.txt" >/dev/null
uv pip install --python "$BUNDLED_PY" -r "$DIST_DIR/requirements.txt" >/dev/null
uv pip install --python "$BUNDLED_PY" --no-deps "$DIST_DIR"/agentic_os-*.whl >/dev/null

SITE_PACKAGES="$STAGING/runtime/python/lib/python3.12/site-packages"
if [[ ! -f "$SITE_PACKAGES/agentic_os/api.py" ]]; then
  echo "prepare-desktop-bundle: agentic_os package not materialized" >&2
  exit 1
fi
if grep -rq "$REPO_ROOT/src" "$SITE_PACKAGES"/*.pth 2>/dev/null; then
  echo "prepare-desktop-bundle: staged runtime references the repo (editable leak)" >&2
  exit 1
fi

# Relocation smoke test: copy the runtime elsewhere and import the
# package with the copied interpreter — proves no build-path coupling.
RELOC_DIR="$(mktemp -d)"
cp -R "$STAGING/runtime/python/." "$RELOC_DIR/python/"
RELOC_PY="$RELOC_DIR/python/bin/python3.12"
RELOC_LIB="$RELOC_DIR/python/lib/libpython3.12.dylib"
if [[ ! -f "$RELOC_PY" || -L "$RELOC_PY" || ! -f "$RELOC_LIB" ]]; then
  echo "prepare-desktop-bundle: relocated runtime is incomplete" >&2
  exit 1
fi
RELOC_VERSION="$(
  PYTHONDONTWRITEBYTECODE=1 "$RELOC_PY" -B \
    -c 'from agentic_os import __version__; print(__version__)'
)"
rm -rf "$RELOC_DIR"
echo "prepare-desktop-bundle: relocation smoke ok (agentic_os ${RELOC_VERSION})"

# Python bytecode inside a signed app bundle is immutable release content.
# Ship source-only runtime files and prevent the packaged daemon from creating
# or updating __pycache__ after launch.
find "$STAGING/runtime/python" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$STAGING/runtime/python" -type d -name __pycache__ -prune -exec rm -rf {} +
if find "$STAGING/runtime/python" \
  \( -type d -name __pycache__ -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
  -print -quit | grep -q .; then
  echo "prepare-desktop-bundle: bytecode cache remains in staged runtime" >&2
  exit 1
fi

echo "prepare-desktop-bundle: ok"
