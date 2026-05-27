import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentic_os.api import create_app


def write_registry(
    path: Path,
    command: list[str] | None = None,
    cwd_mode: str = "optional",
    env: dict[str, str] | None = None,
) -> None:
    if command is None:
        command = ["/usr/bin/printf", "%s", "{{message}}"]
    env_block = f"env = {_toml_inline_table(env)}\n" if env is not None else ""
    path.write_text(
        f"""
[[agents]]
id = "shell"
label = "Shell"
command = {json.dumps(command)}
cwd_mode = {json.dumps(cwd_mode)}
{env_block}\
stop_policy = "process_group"
""",
        encoding="utf-8",
    )


def make_client(
    tmp_path: Path,
    command: list[str] | None = None,
    cwd_mode: str = "optional",
    env: dict[str, str] | None = None,
) -> TestClient:
    registry = tmp_path / "agents.toml"
    write_registry(registry, command=command, cwd_mode=cwd_mode, env=env)
    return TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))


def _toml_inline_table(values: dict[str, str]) -> str:
    entries = ", ".join(f"{json.dumps(key)} = {json.dumps(value)}" for key, value in values.items())
    return f"{{ {entries} }}"


def test_api_lists_agents(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/agents")

    assert response.status_code == 200
    assert response.json()["agents"][0]["id"] == "shell"


def test_api_returns_404_for_unknown_agent_lookup(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/agents/missing")

    assert response.status_code == 404


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


def test_api_returns_failed_session_for_empty_registry_command(tmp_path: Path) -> None:
    client = make_client(tmp_path, command=[])

    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})

    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "failed"

    sessions = client.get("/sessions").json()["sessions"]
    assert all(session["status"] != "queued" for session in sessions)

    logs = client.get(f"/sessions/{body['id']}/logs", params={"stream": "stderr"})
    assert logs.status_code == 200
    assert "empty argv" in logs.json()["entries"][-1]["line"]


def test_api_merges_registry_env_into_child_process(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        command=[
            sys.executable,
            "-c",
            "import os; print(os.environ['AGENTIC_OS_ENV_PROBE'], end='')",
        ],
        env={"AGENTIC_OS_ENV_PROBE": "visible"},
    )

    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})

    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"
    logs = client.get(f"/sessions/{run.json()['id']}/logs")
    assert logs.json()["entries"][0]["line"] == "visible"


def test_api_retry_preserves_registry_env(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        command=[
            sys.executable,
            "-c",
            "import os; print(os.environ['AGENTIC_OS_RETRY_ENV'], end='')",
        ],
        env={"AGENTIC_OS_RETRY_ENV": "retry-visible"},
    )
    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})
    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"

    retry = client.post(f"/sessions/{run.json()['id']}/retry")

    assert retry.status_code == 200
    assert retry.json()["status"] == "succeeded"
    logs = client.get(f"/sessions/{retry.json()['id']}/logs")
    assert logs.json()["entries"][0]["line"] == "retry-visible"


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


def test_api_rejects_repeated_stop_of_stopped_session(tmp_path: Path) -> None:
    client = make_client(tmp_path, command=[sys.executable, "-c", "import time; time.sleep(5)"])
    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"})
    assert run.status_code == 200
    session_id = run.json()["id"]

    stop = client.post(f"/sessions/{session_id}/stop")
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopped"

    repeated_stop = client.post(f"/sessions/{session_id}/stop")

    assert repeated_stop.status_code == 409


def test_api_returns_400_for_unknown_agent_on_run(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/sessions",
        json={"agent_id": "missing", "cwd": str(tmp_path), "message": "OK"},
    )

    assert response.status_code == 400


def test_api_returns_400_for_invalid_cwd_on_run(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path / "missing"), "message": "OK"},
    )

    assert response.status_code == 400


def test_api_returns_400_when_required_cwd_is_omitted(tmp_path: Path) -> None:
    client = make_client(tmp_path, cwd_mode="required")

    response = client.post("/sessions", json={"agent_id": "shell", "message": "OK"})

    assert response.status_code == 400


def test_api_returns_400_for_file_cwd_and_creates_no_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    cwd_file = tmp_path / "cwd.txt"
    cwd_file.write_text("not a directory", encoding="utf-8")

    response = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(cwd_file), "message": "OK"},
    )

    assert response.status_code == 400
    assert client.get("/sessions").json()["sessions"] == []


@pytest.mark.parametrize(
    "case",
    ["missing_message", "missing_agent_id", "non_string_message"],
)
def test_api_returns_400_for_invalid_session_request_body(tmp_path: Path, case: str) -> None:
    client = make_client(tmp_path)
    payloads: dict[str, dict[str, object]] = {
        "missing_message": {"agent_id": "shell", "cwd": str(tmp_path)},
        "missing_agent_id": {"cwd": str(tmp_path), "message": "OK"},
        "non_string_message": {
            "agent_id": "shell",
            "cwd": str(tmp_path),
            "message": 123,
        },
    }

    response = client.post("/sessions", json=payloads[case])

    assert response.status_code == 400


def test_api_keeps_unrelated_validation_errors_as_422(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/sessions/missing/logs", params={"after": -1})

    assert response.status_code == 422
