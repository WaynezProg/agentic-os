import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from agentic_os.api import create_app


def write_registry(path: Path, command: list[str] | None = None) -> None:
    command = command or ["/usr/bin/printf", "%s", "{{message}}"]
    path.write_text(
        f"""
[[agents]]
id = "shell"
label = "Shell"
command = {json.dumps(command)}
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )


def make_client(tmp_path: Path, command: list[str] | None = None) -> TestClient:
    registry = tmp_path / "agents.toml"
    write_registry(registry, command=command)
    return TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))


def test_api_lists_agents(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/agents")

    assert response.status_code == 200
    assert response.json()["agents"][0]["id"] == "shell"


def test_api_runs_session_and_reads_logs(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})
    assert run.status_code == 200
    session_id = run.json()["id"]

    logs = client.get(f"/sessions/{session_id}/logs")
    assert logs.status_code == 200
    assert logs.json()["entries"][0]["line"] == "OK"


def test_api_retries_short_command_and_reads_new_session_logs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})
    assert run.status_code == 200

    retry = client.post(f"/sessions/{run.json()['id']}/retry")

    assert retry.status_code == 200
    assert retry.json()["id"] != run.json()["id"]
    assert retry.json()["status"] == "succeeded"

    logs = client.get(f"/sessions/{retry.json()['id']}/logs")
    assert logs.status_code == 200
    assert logs.json()["entries"][0]["line"] == "OK"


def test_api_rejects_retry_of_running_session(tmp_path: Path) -> None:
    client = make_client(tmp_path, command=[sys.executable, "-c", "import time; time.sleep(5)"])
    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})
    assert run.status_code == 200
    session_id = run.json()["id"]

    try:
        retry = client.post(f"/sessions/{session_id}/retry")

        assert retry.status_code == 409
    finally:
        client.post(f"/sessions/{session_id}/stop")


def test_api_rejects_stop_of_terminal_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})
    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"

    stop = client.post(f"/sessions/{run.json()['id']}/stop")

    assert stop.status_code == 409


def test_api_returns_404_for_unknown_agent_on_run(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/sessions",
        json={"agent_id": "missing", "cwd": str(tmp_path), "message": "OK"},
    )

    assert response.status_code == 404


def test_api_returns_400_for_invalid_cwd_on_run(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path / "missing"), "message": "OK"},
    )

    assert response.status_code == 400
