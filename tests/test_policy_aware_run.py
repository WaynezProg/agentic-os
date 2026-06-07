from pathlib import Path

from fastapi.testclient import TestClient

from agentic_os.api import create_app


def _write_registry(path: Path) -> None:
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


def _make_client(tmp_path: Path) -> TestClient:
    registry = tmp_path / "agents.toml"
    _write_registry(registry)
    return TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))


def _set_policy(client: TestClient, agent_id: str, **overrides: object) -> None:
    payload = {
        "enabled": True,
        "readonly": False,
        "allowed_skill_ids": [],
        "allowed_mcp_server_ids": [],
        "allowed_tool_names": [],
        "approval_required_tool_names": [],
        "allowed_model_ids": [],
        "cwd_roots": [],
        "rate_limit_per_minute": 60,
        **overrides,
    }
    resp = client.post(f"/policy/{agent_id}", json=payload)
    assert resp.status_code == 200


# -- Policy-aware run tests --


def test_session_allowed_when_no_policy_configured(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )

    assert run.status_code == 200
    assert run.json()["status"] in ("succeeded", "running", "queued")


def test_session_allowed_when_policy_allows(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _set_policy(client, "shell", cwd_roots=[str(tmp_path)])

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )

    assert run.status_code == 200
    assert run.json()["status"] in ("succeeded", "running", "queued")


def test_session_denied_when_cwd_outside_roots(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _set_policy(client, "shell", cwd_roots=["/nonexistent/allowed"])

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )

    assert run.status_code == 403
    body = run.json()
    assert body["decision"] == "deny"
    assert "session_id" in body


def test_policy_rollback_re_enables_launch_gate(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _set_policy(client, "shell", cwd_roots=[str(tmp_path)])

    allowed = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )
    assert allowed.status_code == 200

    mutation = client.post(
        "/policy/shell",
        json={
            "enabled": False,
            "readonly": False,
            "allowed_skill_ids": [],
            "allowed_mcp_server_ids": [],
            "allowed_tool_names": [],
            "approval_required_tool_names": [],
            "allowed_model_ids": [],
            "cwd_roots": [str(tmp_path)],
            "rate_limit_per_minute": 60,
        },
    )
    assert mutation.status_code == 200
    patch_id = mutation.json()["patch_id"]

    denied = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )
    assert denied.status_code == 403

    rollback = client.post(f"/policy/shell/rollback?to={patch_id}")
    assert rollback.status_code == 200

    allowed_again = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )
    assert allowed_again.status_code == 200


def test_session_denied_when_policy_disabled(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _set_policy(client, "shell", enabled=False)

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )

    assert run.status_code == 403
    assert run.json()["decision"] == "deny"


def test_denied_session_records_policy_denied_event(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _set_policy(client, "shell", cwd_roots=["/nonexistent/allowed"])

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )
    session_id = run.json()["session_id"]

    events = client.get(f"/sessions/{session_id}/events")
    assert events.status_code == 200
    event_types = [e["event_type"] for e in events.json()["events"]]
    assert "policy_denied" in event_types


def test_denied_session_is_auditable_with_failed_status(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _set_policy(client, "shell", cwd_roots=["/nonexistent/allowed"])

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )
    session_id = run.json()["session_id"]

    session = client.get(f"/sessions/{session_id}")
    assert session.status_code == 200
    assert session.json()["status"] == "failed"


def test_denied_session_appears_in_session_list(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _set_policy(client, "shell", cwd_roots=["/nonexistent/allowed"])

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )
    session_id = run.json()["session_id"]

    sessions = client.get("/sessions")
    ids = [s["id"] for s in sessions.json()["sessions"]]
    assert session_id in ids


def test_session_requires_approval_when_start_requires_approval(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _set_policy(
        client,
        "shell",
        cwd_roots=[str(tmp_path)],
        approval_required_tool_names=["session.start"],
    )

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )

    assert run.status_code == 409
    body = run.json()
    assert body["decision"] == "approval_required"
    session_id = body["session_id"]

    session = client.get(f"/sessions/{session_id}")
    assert session.json()["status"] == "failed"
    assert session.json()["pid"] is None

    events = client.get(f"/sessions/{session_id}/events")
    event_types = [e["event_type"] for e in events.json()["events"]]
    assert "policy_approval_required" in event_types


# -- Events API tests --


def test_events_endpoint_returns_empty_for_clean_session(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"},
    )
    session_id = run.json()["id"]

    events = client.get(f"/sessions/{session_id}/events")

    assert events.status_code == 200
    assert events.json()["events"] == []


def test_events_endpoint_returns_404_for_missing_session(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    events = client.get("/sessions/s_nonexistent/events")

    assert events.status_code == 404


def test_events_endpoint_returns_launch_failed_for_bad_command(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    registry.write_text(
        """
[[agents]]
id = "bad"
label = "Bad"
command = []
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    run = client.post(
        "/sessions",
        json={"agent_id": "bad", "cwd": str(tmp_path), "message": "x"},
    )
    session_id = run.json()["id"]

    events = client.get(f"/sessions/{session_id}/events")
    assert events.status_code == 200
    event_types = [e["event_type"] for e in events.json()["events"]]
    assert "launch_failed" in event_types


# -- Retry policy enforcement tests (P3.6) --


def test_retry_denied_when_policy_denies_cwd(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )
    assert run.status_code == 200
    original_id = run.json()["id"]

    _set_policy(client, "shell", cwd_roots=["/nonexistent/allowed"])

    retry = client.post(f"/sessions/{original_id}/retry")

    assert retry.status_code == 403
    body = retry.json()
    assert body["decision"] == "deny"
    assert "session_id" in body
    assert body["session_id"] != original_id


def test_retry_denied_session_cannot_produce_running_process(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _set_policy(client, "shell", cwd_roots=["/nonexistent/allowed"])

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "denied"},
    )
    assert run.status_code == 403
    denied_id = run.json()["session_id"]

    retry = client.post(f"/sessions/{denied_id}/retry")

    assert retry.status_code == 403
    audit_id = retry.json()["session_id"]

    session = client.get(f"/sessions/{audit_id}")
    assert session.json()["status"] == "failed"
    assert session.json()["pid"] is None


def test_retry_approval_required_returns_409(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )
    assert run.status_code == 200
    original_id = run.json()["id"]

    _set_policy(
        client,
        "shell",
        cwd_roots=[str(tmp_path)],
        approval_required_tool_names=["session.start"],
    )

    retry = client.post(f"/sessions/{original_id}/retry")

    assert retry.status_code == 409
    body = retry.json()
    assert body["decision"] == "approval_required"
    audit_id = body["session_id"]

    events = client.get(f"/sessions/{audit_id}/events")
    event_types = [e["event_type"] for e in events.json()["events"]]
    assert "policy_approval_required" in event_types


def test_retry_allowed_when_policy_permits(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    _set_policy(client, "shell", cwd_roots=[str(tmp_path)])

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )
    assert run.status_code == 200
    original_id = run.json()["id"]

    retry = client.post(f"/sessions/{original_id}/retry")

    assert retry.status_code == 200
    assert retry.json()["id"] != original_id
    assert retry.json()["status"] in ("succeeded", "running", "queued")


def test_retry_allowed_when_no_policy_configured(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "hello"},
    )
    assert run.status_code == 200
    original_id = run.json()["id"]

    retry = client.post(f"/sessions/{original_id}/retry")

    assert retry.status_code == 200
    assert retry.json()["id"] != original_id
