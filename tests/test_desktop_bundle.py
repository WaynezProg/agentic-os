"""Tests for prepare-desktop-bundle.sh staging layout."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "apps/desktop/src-tauri/bundle-resources/agentic-os"


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
