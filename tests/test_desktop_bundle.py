"""Tests for prepare-desktop-bundle.sh staging layout."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "apps/desktop/src-tauri/bundle-resources/agentic-os"


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
    # Relocatable runtime: package materialized inside the bundled
    # python, and nothing points back at the repo checkout.
    site = STAGING / "runtime/python/lib/python3.12/site-packages"
    assert (site / "agentic_os/api.py").is_file()
    for pth in site.glob("*.pth"):
        assert "src" not in pth.read_text(), f"repo reference leaked via {pth.name}"


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
