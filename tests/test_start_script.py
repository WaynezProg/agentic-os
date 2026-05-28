from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = ROOT / "scripts" / "start-local.sh"
README = ROOT / "README.md"


def test_start_local_script_exists_and_is_executable() -> None:
    assert START_SCRIPT.is_file()
    assert os.access(START_SCRIPT, os.X_OK)


def test_start_local_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(START_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_start_local_script_launches_daemon_and_static_ui_without_seed_data() -> None:
    script = START_SCRIPT.read_text(encoding="utf-8")

    assert "rtk uv run agentd serve" in script
    assert "rtk uv run python -m http.server" in script
    assert '--directory "$ROOT_DIR/apps/web"' in script
    assert "AGENTIC_OS_PORT" in script
    assert "AGENTIC_OS_UI_PORT" in script
    assert "trap cleanup EXIT INT TERM" in script
    for forbidden in [
        "agentctl skills upsert",
        "agentctl mcp upsert",
        "agentctl policy set",
    ]:
        assert forbidden not in script


def test_readme_documents_one_command_local_start() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "One-command local start" in readme
    assert "rtk bash scripts/start-local.sh" in readme
    assert "AGENTIC_OS_PORT" in readme
    assert "AGENTIC_OS_UI_PORT" in readme
