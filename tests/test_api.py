from pathlib import Path

from fastapi.testclient import TestClient

from agentic_os.api import create_app


def write_registry(path: Path) -> None:
    path.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "%s", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )


def test_api_lists_agents(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    write_registry(registry)
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    response = client.get("/agents")

    assert response.status_code == 200
    assert response.json()["agents"][0]["id"] == "shell"


def test_api_runs_session_and_reads_logs(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    write_registry(registry)
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})
    assert run.status_code == 200
    session_id = run.json()["id"]

    logs = client.get(f"/sessions/{session_id}/logs")
    assert logs.status_code == 200
    assert logs.json()["entries"][0]["line"] == "OK"
