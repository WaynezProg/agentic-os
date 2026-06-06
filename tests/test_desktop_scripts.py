"""Tests for desktop lifecycle shell scripts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_script(script: str, command: str, *, env: dict[str, str] | None = None) -> dict[str, object]:
    import os

    merged = os.environ.copy()
    if env:
        merged.update(env)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / script), command],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
        env=merged,
    )
    return json.loads(result.stdout)


def test_desktop_daemon_status_json_when_down(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_OS_STATE_DIR", str(tmp_path / ".agentic-os"))
    payload = _run_script("desktop-daemon.sh", "status")
    assert payload["api_url"] == "http://127.0.0.1:8767"
    assert payload["health"] in ("ok", "down")
    assert isinstance(payload["running"], bool)
    assert isinstance(payload["managed"], bool)


def test_desktop_ui_status_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_OS_STATE_DIR", str(tmp_path / ".agentic-os"))
    payload = _run_script("desktop-ui.sh", "status")
    assert payload["ui_url"] == "http://127.0.0.1:5173"
    assert isinstance(payload["running"], bool)
    assert isinstance(payload["managed"], bool)
