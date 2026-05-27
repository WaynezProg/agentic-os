import json
from pathlib import Path

from fastapi.testclient import TestClient

from agentic_os.api import create_app


def write_smoke_registry(path: Path) -> None:
    path.write_text(
        f"""
[[agents]]
id = "shell"
label = "Shell"
command = {json.dumps(["/usr/bin/printf", "%s", "{{message}}"])}
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )


def make_smoke_client(tmp_path: Path) -> TestClient:
    registry_path = tmp_path / "agents.toml"
    write_smoke_registry(registry_path)
    return TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry_path))


def test_shell_run_logs_retry_end_to_end_smoke(tmp_path: Path) -> None:
    client = make_smoke_client(tmp_path)

    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})

    assert run.status_code == 200
    original = run.json()
    assert original["status"] == "succeeded"

    logs = client.get(f"/sessions/{original['id']}/logs")
    assert logs.status_code == 200
    assert [entry["line"] for entry in logs.json()["entries"]] == ["OK"]

    retry = client.post(f"/sessions/{original['id']}/retry")

    assert retry.status_code == 200
    retried = retry.json()
    assert retried["status"] == "succeeded"
    assert retried["id"] != original["id"]

    sessions = client.get("/sessions")
    assert sessions.status_code == 200
    session_ids = {session["id"] for session in sessions.json()["sessions"]}
    assert {original["id"], retried["id"]} <= session_ids

    for session in (original, retried):
        assert Path(session["artifact_dir"]).is_dir()
        assert Path(session["stdout_log"]).is_file()
        assert Path(session["stderr_log"]).is_file()
