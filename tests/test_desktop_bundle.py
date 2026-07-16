"""Tests for prepare-desktop-bundle.sh staging layout."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "apps/desktop/src-tauri/bundle-resources/agentic-os"


def test_desktop_build_script_targets_app_bundle() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["desktop:build"].endswith("tauri build --bundles app")


def test_packaged_daemon_disables_bytecode_writes() -> None:
    script = (ROOT / "scripts/desktop-daemon.sh").read_text(encoding="utf-8")

    assert 'PYTHONDONTWRITEBYTECODE=1 nohup "$AGENTD_PY" -B "$AGENTD_BIN" serve' in script


def test_tauri_window_and_csp_are_production_safe() -> None:
    config = json.loads(
        (ROOT / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )
    window = config["app"]["windows"][0]
    assert window["width"] == 1280
    assert window["height"] == 820
    assert window["minWidth"] == 960
    assert window["minHeight"] == 640

    csp = config["app"]["security"]["csp"]
    assert csp
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "connect-src" in csp
    assert "ipc:" in csp
    assert "http://127.0.0.1:*" in csp
    assert "https:" not in csp
    assert config["bundle"]["macOS"]["signingIdentity"] == "-"


@pytest.mark.skipif(sys.platform != "darwin", reason="stages a macOS app bundle")
def test_prepare_desktop_bundle_layout() -> None:
    env = os.environ.copy()
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/prepare-desktop-bundle.sh")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0
    assert (STAGING / "scripts/desktop-daemon.sh").is_file()
    assert (STAGING / "scripts/desktop-ui.sh").is_file()
    assert (STAGING / "scripts/lib/desktop-common.sh").is_file()
    assert (STAGING / "web/index.html").is_file()
    assert (STAGING / "registry/agents.toml").is_file()
    agentd = STAGING / "runtime/python/bin/agentd"
    assert agentd.is_file()
    assert os.access(agentd, os.X_OK)
    python = STAGING / "runtime/python/bin/python3.12"
    libpython = STAGING / "runtime/python/lib/libpython3.12.dylib"
    assert python.is_file()
    assert not python.is_symlink()
    assert libpython.is_file()
    for link in (STAGING / "runtime/python").rglob("*"):
        if link.is_symlink():
            assert not os.readlink(link).startswith("/"), f"absolute runtime symlink: {link}"
    # Relocatable runtime: package materialized inside the bundled
    # python, and nothing points back at the repo checkout.
    site = STAGING / "runtime/python/lib/python3.12/site-packages"
    assert (site / "agentic_os/api.py").is_file()
    for pth in site.glob("*.pth"):
        assert "src" not in pth.read_text(), f"repo reference leaked via {pth.name}"
    assert not list((STAGING / "runtime/python").rglob("*.pyc"))
    assert not list((STAGING / "runtime/python").rglob("__pycache__"))
    bytecode_env = env | {"PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [
            str(python),
            "-B",
            "-c",
            "from agentic_os import __version__; print(__version__)",
        ],
        env=bytecode_env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "1.0.1"
    assert not list((STAGING / "runtime/python").rglob("*.pyc"))
    assert not list((STAGING / "runtime/python").rglob("__pycache__"))


def test_desktop_ui_start_is_noop_in_bundle_mode(tmp_path: Path) -> None:
    """Packaged app serves UI via tauri assets — no loopback server.

    A python http.server in bundle mode is a useless extra process and
    an orphan risk on crash (it has no parent watchdog).
    """
    bundle = tmp_path / "bundle"
    (bundle / "scripts" / "lib").mkdir(parents=True)
    (bundle / "web").mkdir()
    agentd = bundle / "runtime" / "python" / "bin" / "agentd"
    agentd.parent.mkdir(parents=True)
    agentd.write_text("#!/bin/sh\n", encoding="utf-8")
    agentd.chmod(0o755)
    for rel in ("scripts/desktop-ui.sh", "scripts/lib/desktop-common.sh"):
        (bundle / rel).write_bytes((ROOT / rel).read_bytes())
        (bundle / rel).chmod(0o755)

    env = os.environ.copy()
    env["AGENTIC_OS_BUNDLE_ROOT"] = str(bundle)
    env["AGENTIC_OS_STATE_DIR"] = str(tmp_path / "state")
    env["AGENTIC_OS_UI_PORT"] = "59731"

    result = subprocess.run(
        ["bash", str(bundle / "scripts" / "desktop-ui.sh"), "start"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        assert result.returncode == 0, result.stderr
        assert "skipped" in result.stderr
        probe = subprocess.run(
            ["bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/59731"],
            capture_output=True,
            timeout=5,
        )
        assert probe.returncode != 0, "a ui server is listening but must not be"
    finally:
        subprocess.run(
            ["bash", str(bundle / "scripts" / "desktop-ui.sh"), "stop"],
            env=env,
            capture_output=True,
            timeout=30,
        )
