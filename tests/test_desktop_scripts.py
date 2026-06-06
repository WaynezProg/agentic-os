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


def _make_bundle_fixture(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    scripts = bundle / "scripts/lib"
    scripts.mkdir(parents=True)
    for name in ("desktop-daemon.sh", "desktop-ui.sh"):
        (bundle / "scripts" / name).write_text(
            (ROOT / "scripts" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    (scripts / "desktop-common.sh").write_text(
        (ROOT / "scripts/lib/desktop-common.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (bundle / "web").mkdir()
    (bundle / "web/index.html").write_text("<html></html>", encoding="utf-8")
    (bundle / "registry").mkdir()
    (bundle / "registry/agents.toml").write_text("[agents]\n", encoding="utf-8")
    runtime = bundle / "runtime/.venv/bin"
    runtime.mkdir(parents=True)
    agentd = runtime / "agentd"
    agentd.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    agentd.chmod(0o755)
    return bundle


def _run_bundle_script(bundle: Path, script: str, command: str, *, env: dict[str, str]) -> dict[str, object]:
    import os

    merged = os.environ.copy()
    merged.update(env)
    merged["AGENTIC_OS_BUNDLE_ROOT"] = str(bundle)
    result = subprocess.run(
        ["bash", str(bundle / "scripts" / script), command],
        capture_output=True,
        text=True,
        check=True,
        cwd=bundle,
        env=merged,
    )
    return json.loads(result.stdout)


def test_desktop_daemon_status_with_bundle_root(tmp_path, monkeypatch) -> None:
    bundle = _make_bundle_fixture(tmp_path)
    state_dir = tmp_path / ".agentic-os"
    monkeypatch.setenv("AGENTIC_OS_STATE_DIR", str(state_dir))
    payload = _run_bundle_script(
        bundle,
        "desktop-daemon.sh",
        "status",
        env={"AGENTIC_OS_STATE_DIR": str(state_dir)},
    )
    assert payload["api_url"] == "http://127.0.0.1:8767"
    assert payload["health"] in ("ok", "down")


def test_desktop_ui_status_with_bundle_root(tmp_path, monkeypatch) -> None:
    bundle = _make_bundle_fixture(tmp_path)
    state_dir = tmp_path / ".agentic-os"
    payload = _run_bundle_script(
        bundle,
        "desktop-ui.sh",
        "status",
        env={"AGENTIC_OS_STATE_DIR": str(state_dir)},
    )
    assert payload["ui_url"] == "http://127.0.0.1:5173"


def test_desktop_bundle_default_state_dir_is_home(tmp_path, monkeypatch) -> None:
    bundle = _make_bundle_fixture(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    import os

    merged = os.environ.copy()
    merged["AGENTIC_OS_BUNDLE_ROOT"] = str(bundle)
    merged.pop("AGENTIC_OS_STATE_DIR", None)
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{bundle}/scripts/lib/desktop-common.sh"; desktop_state_dir',
        ],
        capture_output=True,
        text=True,
        check=True,
        env=merged,
    )
    assert result.stdout.strip() == str(home / ".agentic-os")


def test_desktop_reconcile_clears_stale_pid(tmp_path, monkeypatch) -> None:
    bundle = _make_bundle_fixture(tmp_path)
    state_dir = tmp_path / ".agentic-os"
    runtime_dir = state_dir / "desktop"
    runtime_dir.mkdir(parents=True)
    pid_file = runtime_dir / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    payload = _run_bundle_script(
        bundle,
        "desktop-daemon.sh",
        "reconcile",
        env={"AGENTIC_OS_STATE_DIR": str(state_dir)},
    )
    assert not pid_file.exists()
    assert payload["health"] in ("ok", "down")
