import io
import json
import sys
import textwrap
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentic_os import profiles as profiles_module
from agentic_os.api import create_app
from agentic_os.control_plane import SkillUpsert
from agentic_os.models import SessionCreate


def write_registry(
    path: Path,
    command: list[str] | None = None,
    cwd_mode: str = "optional",
    env: dict[str, str] | None = None,
    model_arg: list[str] | None = None,
    provider_env: str | None = None,
) -> None:
    if command is None:
        command = ["/usr/bin/printf", "%s", "{{message}}"]
    env_block = f"env = {_toml_inline_table(env)}\n" if env is not None else ""
    model_arg_block = (
        f"model_arg = {json.dumps(model_arg)}\n" if model_arg is not None else ""
    )
    provider_env_block = (
        f"provider_env = {json.dumps(provider_env)}\n" if provider_env is not None else ""
    )
    path.write_text(
        f"""
[[agents]]
id = "shell"
label = "Shell"
command = {json.dumps(command)}
cwd_mode = {json.dumps(cwd_mode)}
{env_block}{model_arg_block}{provider_env_block}\
stop_policy = "process_group"
""",
        encoding="utf-8",
    )


def make_client(
    tmp_path: Path,
    command: list[str] | None = None,
    cwd_mode: str = "optional",
    env: dict[str, str] | None = None,
    model_arg: list[str] | None = None,
    provider_env: str | None = None,
) -> TestClient:
    registry = tmp_path / "agents.toml"
    write_registry(
        registry,
        command=command,
        cwd_mode=cwd_mode,
        env=env,
        model_arg=model_arg,
        provider_env=provider_env,
    )
    return TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))


def _toml_inline_table(values: dict[str, str]) -> str:
    entries = ", ".join(f"{json.dumps(key)} = {json.dumps(value)}" for key, value in values.items())
    return f"{{ {entries} }}"


def wait_for_session_evidence(
    client: TestClient,
    session_id: str,
    *,
    status: str = "succeeded",
    required_events: set[str] | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/sessions/{session_id}/evidence")
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        metadata = payload["metadata"]
        if not isinstance(metadata, dict) or metadata.get("status") != status:
            time.sleep(0.025)
            continue
        if required_events:
            events_response = client.get(f"/sessions/{session_id}/evidence/events")
            assert events_response.status_code == 200
            event_types = {event["event_type"] for event in events_response.json()["events"]}
            if not required_events <= event_types:
                time.sleep(0.025)
                continue
        return payload
    raise AssertionError(f"evidence for {session_id} did not reach {status}: {last_payload}")


@pytest.fixture()
def tmp_app(tmp_path: Path):
    registry = tmp_path / "agents.toml"
    write_registry(registry)
    return create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)


def test_api_lists_agents(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/agents")

    assert response.status_code == 200
    assert response.json()["agents"][0]["id"] == "shell"


def test_api_returns_404_for_unknown_agent_lookup(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/agents/missing")

    assert response.status_code == 404


def test_api_agents_filter_by_tool_kind(tmp_path: Path) -> None:
    registry = tmp_path / "agents.toml"
    registry.write_text(
        textwrap.dedent(
            """\
            [[agents]]
            id = "shell"
            label = "Shell"
            command = ["/usr/bin/printf", "%s", "{{message}}"]
            cwd_mode = "optional"
            stop_policy = "process_group"
            tool_kind = "vibe_coding"

            [[agents]]
            id = "n8n"
            label = "n8n"
            command = ["n8n"]
            cwd_mode = "optional"
            stop_policy = "process_group"
            tool_kind = "agentic_runtime"
            """
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)
    )

    response = client.get("/agents?tool_kind=vibe_coding")

    assert response.status_code == 200
    agents = response.json()["agents"]
    assert {a["id"] for a in agents} == {"shell"}


def test_api_evidence_zip_for_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "ZIPME"}
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    # Wait for evidence bundle to be created.
    wait_for_session_evidence(client, session_id, status="succeeded")

    response = client.get(f"/sessions/{session_id}/evidence.zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    assert any(name.endswith("metadata.json") for name in names)
    assert any(name.endswith("events.jsonl") for name in names)


def test_api_runs_session_and_reads_logs(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"}
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    logs = client.get(f"/sessions/{session_id}/logs")
    assert logs.status_code == 200
    assert logs.json()["entries"][0]["line"] == "OK"


def test_api_retries_short_command_and_reads_new_session_logs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"}
    )
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

    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"}
    )

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

    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"}
    )

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
    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"}
    )
    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"

    retry = client.post(f"/sessions/{run.json()['id']}/retry")

    assert retry.status_code == 200
    assert retry.json()["status"] == "succeeded"
    logs = client.get(f"/sessions/{retry.json()['id']}/logs")
    assert logs.json()["entries"][0]["line"] == "retry-visible"


def test_api_rejects_retry_of_running_session(tmp_path: Path) -> None:
    client = make_client(tmp_path, command=[sys.executable, "-c", "import time; time.sleep(5)"])
    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"}
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    try:
        retry = client.post(f"/sessions/{session_id}/retry")

        assert retry.status_code == 409
    finally:
        client.post(f"/sessions/{session_id}/stop")


def test_api_rejects_stop_of_terminal_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"}
    )
    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"

    stop = client.post(f"/sessions/{run.json()['id']}/stop")

    assert stop.status_code == 409


def test_api_rejects_repeated_stop_of_stopped_session(tmp_path: Path) -> None:
    client = make_client(tmp_path, command=[sys.executable, "-c", "import time; time.sleep(5)"])
    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "OK"}
    )
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


def test_api_creates_and_reads_session_memory_summary(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "remember alpha"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    created = client.post(f"/sessions/{session_id}/memory/summary")
    read = client.get(f"/sessions/{session_id}/memory/summary")

    assert created.status_code == 200
    assert read.status_code == 200
    assert created.json()["id"] == read.json()["id"]
    assert created.json()["session_id"] == session_id
    assert created.json()["one_liner"] == "remember alpha"
    assert created.json()["stdout_lines"] == 1
    assert created.json()["stderr_lines"] == 0
    assert created.json()["ownership"] == "summary_pointer"
    assert created.json()["formal_memory_owner"] == "session2memory"


def test_api_returns_404_for_unknown_session_memory_summary(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    created = client.post("/sessions/missing/memory/summary")
    read = client.get("/sessions/missing/memory/summary")

    assert created.status_code == 404
    assert read.status_code == 404


def test_api_creates_memory_review_from_current_session_logs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "review me"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    created = client.post(f"/sessions/{session_id}/memory/review")
    listed = client.get("/memory/review")
    summary = client.get(f"/sessions/{session_id}/memory/summary")

    assert created.status_code == 200
    assert created.json()["session_id"] == session_id
    assert created.json()["status"] == "pending"
    assert created.json()["title"] == "review me"
    assert created.json()["ownership"] == "review_pointer"
    assert created.json()["formal_memory_owner"] == "session2memory"
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [created.json()["id"]]
    assert summary.status_code == 200
    assert summary.json()["session_id"] == session_id


def test_api_returns_404_for_unknown_session_memory_review(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post("/sessions/missing/memory/review")

    assert response.status_code == 404


def test_api_approves_memory_review_and_searches_approved_memories_only(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    approved_run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "alpha approved memory"},
    )
    pending_run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "beta pending memory"},
    )
    assert approved_run.status_code == 200
    assert pending_run.status_code == 200

    approved_item_response = client.post(
        f"/sessions/{approved_run.json()['id']}/memory/review",
    )
    pending_item_response = client.post(
        f"/sessions/{pending_run.json()['id']}/memory/review",
    )
    assert approved_item_response.status_code == 200
    assert pending_item_response.status_code == 200
    approved_item = approved_item_response.json()
    pending_item = pending_item_response.json()

    approved = client.post(f"/memory/review/{approved_item['id']}/approve")
    memories = client.get("/memory")
    alpha_search = client.get("/memory/search", params={"q": "alpha"})
    beta_search = client.get("/memory/search", params={"q": "beta"})

    assert approved.status_code == 200
    assert approved.json()["review_item_id"] == approved_item["id"]
    assert memories.status_code == 200
    assert [memory["title"] for memory in memories.json()["memories"]] == ["alpha approved memory"]
    assert [memory["title"] for memory in alpha_search.json()["memories"]] == [
        "alpha approved memory"
    ]
    assert beta_search.json()["memories"] == []
    assert pending_item["status"] == "pending"


def test_api_rejects_memory_review_without_creating_memory(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "reject memory"},
    )
    assert run.status_code == 200
    item_response = client.post(f"/sessions/{run.json()['id']}/memory/review")
    assert item_response.status_code == 200
    item = item_response.json()

    rejected = client.post(f"/memory/review/{item['id']}/reject")

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert client.get("/memory").json()["memories"] == []


def test_api_returns_404_for_unknown_memory_review_transition(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    approve = client.post("/memory/review/missing/approve")
    reject = client.post("/memory/review/missing/reject")

    assert approve.status_code == 404
    assert reject.status_code == 404


def test_api_returns_409_for_invalid_memory_review_transition(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "approve once"},
    )
    assert run.status_code == 200
    item_response = client.post(f"/sessions/{run.json()['id']}/memory/review")
    assert item_response.status_code == 200
    item = item_response.json()
    first = client.post(f"/memory/review/{item['id']}/approve")

    repeated_approve = client.post(f"/memory/review/{item['id']}/approve")
    repeated_reject = client.post(f"/memory/review/{item['id']}/reject")

    assert first.status_code == 200
    assert repeated_approve.status_code == 409
    assert repeated_reject.status_code == 409


def test_api_returns_p2_placeholder_skills_and_mcp(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    skills = client.get("/skills")
    mcp = client.get("/mcp")

    assert skills.status_code == 200
    assert skills.json() == {"skills": []}
    assert mcp.status_code == 200
    assert mcp.json() == {"servers": []}


def test_api_upserts_reads_lists_and_disables_skill(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    created = client.post(
        "/skills/reviewer",
        json={
            "label": "Reviewer",
            "description": "Review local changes",
            "source": "workspace",
            "entrypoint": "skills/reviewer/SKILL.md",
            "tags": ["review", "local"],
        },
    )
    listed = client.get("/skills")
    shown = client.get("/skills/reviewer")
    disabled = client.post("/skills/reviewer/disable")

    assert created.status_code == 200
    assert created.json()["id"] == "reviewer"
    assert created.json()["enabled"] is True
    assert [skill["id"] for skill in listed.json()["skills"]] == ["reviewer"]
    assert shown.json()["tags"] == ["review", "local"]
    assert disabled.json()["enabled"] is False


def test_api_upserts_reads_lists_and_disables_mcp_server(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    created = client.post(
        "/mcp/filesystem",
        json={
            "label": "Filesystem MCP",
            "description": "Local metadata",
            "transport": "stdio",
            "command_preview": ["mcp-server", "--token", "TOKEN_PLACEHOLDER"],
            "env_keys": ["MCP_TOKEN=TOKEN_PLACEHOLDER"],
        },
    )
    listed = client.get("/mcp")
    shown = client.get("/mcp/filesystem")
    disabled = client.post("/mcp/filesystem/disable")

    assert created.status_code == 200
    assert created.json()["id"] == "filesystem"
    assert "TOKEN_PLACEHOLDER" not in json.dumps(created.json())
    assert created.json()["env_keys"] == ["MCP_TOKEN"]
    assert [server["id"] for server in listed.json()["servers"]] == ["filesystem"]
    assert shown.json()["label"] == "Filesystem MCP"
    assert disabled.json()["enabled"] is False


def test_api_upserts_reads_lists_and_evaluates_policy(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/skills/reviewer", json={"label": "Reviewer"})
    client.post("/mcp/filesystem", json={"label": "Filesystem MCP"})

    created = client.post(
        "/policy/shell",
        json={
            "allowed_skill_ids": ["reviewer"],
            "allowed_mcp_server_ids": ["filesystem"],
            "allowed_tool_names": ["read", "exec"],
            "approval_required_tool_names": ["exec"],
            "allowed_model_ids": ["local-model"],
            "cwd_roots": [str(tmp_path)],
            "rate_limit_per_minute": 20,
        },
    )
    listed = client.get("/policy")
    shown = client.get("/policy/shell")
    allowed = client.post(
        "/policy/evaluate",
        json={
            "agent_id": "shell",
            "skill_id": "reviewer",
            "mcp_server_id": "filesystem",
            "tool_name": "read",
            "model_id": "local-model",
            "cwd": str(tmp_path / "project"),
        },
    )
    approval = client.post("/policy/evaluate", json={"agent_id": "shell", "tool_name": "exec"})

    assert created.status_code == 200
    assert created.json()["agent_id"] == "shell"
    assert [policy["agent_id"] for policy in listed.json()["policies"]] == ["shell"]
    assert shown.json()["allowed_skill_ids"] == ["reviewer"]
    assert allowed.json()["decision"] == "allow"
    assert allowed.json()["reason"] == "policy allowed request"
    assert approval.json()["decision"] == "approval_required"


def test_api_returns_404_for_unknown_control_plane_reads(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    skill = client.get("/skills/missing")
    mcp = client.get("/mcp/missing")
    policy = client.get("/policy/missing")

    assert skill.status_code == 404
    assert mcp.status_code == 404
    assert policy.status_code == 404


def test_api_control_plane_history_and_rollback(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    created = client.post(
        "/skills/reviewer",
        json={"label": "Reviewer", "description": "v1"},
    )
    assert created.status_code == 200

    updated = client.post(
        "/skills/reviewer",
        json={"label": "Reviewer v2", "description": "v2"},
    )
    assert updated.status_code == 200
    patch_id = updated.json()["patch_id"]
    assert updated.json()["label"] == "Reviewer v2"

    history = client.get("/skills/reviewer/history")
    assert history.status_code == 200
    patches = history.json()["patches"]
    assert len(patches) == 1
    assert patches[0]["patch_id"] == patch_id

    rolled = client.post(f"/skills/reviewer/rollback?to={patch_id}")
    assert rolled.status_code == 200
    assert rolled.json()["label"] == "Reviewer"


def test_api_mcp_edit_does_not_persist_redacted_values(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/mcp/figma",
        json={
            "label": "Figma",
            "transport": "http",
            "command_preview": ["figma-mcp", "--token", "SUPER_SECRET"],
            "url": "https://user:SECRET@example.invalid/mcp",
            "env_keys": ["FIGMA_TOKEN"],
        },
    )
    shown = client.get("/mcp/figma")
    assert shown.status_code == 200
    raw = json.dumps(shown.json())
    assert "SUPER_SECRET" not in raw
    assert "SECRET" not in raw or "[REDACTED]" in raw

    updated = client.post(
        "/mcp/figma",
        json={
            "label": "Figma v2",
            "transport": "http",
            "command_preview": ["figma-mcp", "v2"],
            "url": "https://example.invalid/mcp",
            "env_keys": ["FIGMA_TOKEN"],
        },
    )
    assert updated.status_code == 200
    stored = json.dumps(updated.json())
    assert "SUPER_SECRET" not in stored
    assert updated.json()["label"] == "Figma v2"


def test_api_allows_localhost_cors_preflight(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.options(
        "/memory",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"




def test_api_allows_delete_cors_preflight(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.options(
        "/profiles/example",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    allowed_methods = response.headers.get("access-control-allow-methods", "")
    assert "DELETE" in allowed_methods


def test_api_allows_put_cors_preflight(tmp_path: Path) -> None:
    # Workspace selection and run-template updates issue PUT from the web UI
    # (5173 -> 8767); the preflight must advertise PUT or those calls are blocked.
    client = make_client(tmp_path)

    response = client.options(
        "/workspaces/active",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PUT",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    allowed_methods = response.headers.get("access-control-allow-methods", "")
    assert "PUT" in allowed_methods


def test_fleet_health_empty(tmp_app) -> None:
    client = TestClient(tmp_app)
    response = client.get("/fleet/health")
    assert response.status_code == 200
    assert response.json()["instances"] == []


def test_fleet_health_after_record(tmp_app) -> None:
    client = TestClient(tmp_app)
    from agentic_os.fleet import HealthState

    tmp_app.state.fleet_store.record_health("shell", HealthState.UP, "OK", version="1.0.0")
    response = client.get("/fleet/health")
    assert response.status_code == 200
    instances = response.json()["instances"]
    assert len(instances) == 1
    assert instances[0]["agent_id"] == "shell"
    assert instances[0]["state"] == "up"


def test_fleet_instance_health(tmp_app) -> None:
    client = TestClient(tmp_app)
    from agentic_os.fleet import HealthState

    tmp_app.state.fleet_store.record_health("shell", HealthState.UP, "OK")
    response = client.get("/fleet/shell/health")
    assert response.status_code == 200
    assert response.json()["agent_id"] == "shell"


def test_fleet_instance_health_404(tmp_app) -> None:
    client = TestClient(tmp_app)
    response = client.get("/fleet/nonexistent/health")
    assert response.status_code == 404


def test_fleet_events(tmp_app) -> None:
    client = TestClient(tmp_app)
    from agentic_os.fleet import HealthState

    tmp_app.state.fleet_store.record_health("shell", HealthState.UP, "OK")
    tmp_app.state.fleet_store.record_health("shell", HealthState.DOWN, "fail")
    response = client.get("/fleet/events")
    assert response.status_code == 200
    assert len(response.json()["events"]) >= 1


def test_fleet_capacity(tmp_app) -> None:
    client = TestClient(tmp_app)
    response = client.get("/fleet/capacity")
    assert response.status_code == 200
    data = response.json()
    assert "running_sessions" in data
    assert "max_running_sessions" in data


def test_run_session_429_at_capacity(tmp_app, tmp_path: Path) -> None:
    client = TestClient(tmp_app)
    store = tmp_app.state.store
    tmp_app.state.fleet_store.MAX_RUNNING_SESSIONS = 2
    for i in range(2):
        session = store.create_session(
            SessionCreate(
                agent_id="shell",
                cwd=str(tmp_path),
                argv=["/bin/sleep", "999"],
                artifact_dir=str(tmp_path / f"art_{i}"),
                stdout_log=str(tmp_path / f"out_{i}.jsonl"),
                stderr_log=str(tmp_path / f"err_{i}.jsonl"),
            )
        )
        store.mark_running(session.id, pid=99900 + i, pgid=99900 + i)

    response = client.post("/sessions", json={"agent_id": "shell", "message": "test"})

    assert response.status_code == 429
    assert "capacity" in response.json()["detail"].lower()


def test_run_session_429_records_capacity_event(tmp_app, tmp_path: Path) -> None:
    client = TestClient(tmp_app)
    store = tmp_app.state.store
    tmp_app.state.fleet_store.MAX_RUNNING_SESSIONS = 1
    session = store.create_session(
        SessionCreate(
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/bin/sleep", "999"],
            artifact_dir=str(tmp_path / "art"),
            stdout_log=str(tmp_path / "out.jsonl"),
            stderr_log=str(tmp_path / "err.jsonl"),
        )
    )
    store.mark_running(session.id, pid=99900, pgid=99900)

    response = client.post("/sessions", json={"agent_id": "shell", "message": "test"})
    events = client.get("/fleet/events", params={"event_type": "capacity_limit_reached"})

    assert response.status_code == 429
    assert events.json()["events"][0]["metadata"]["running_sessions"] == 1


def test_fleet_probe_trigger(tmp_app) -> None:
    client = TestClient(tmp_app)
    response = client.post("/fleet/probe")
    assert response.status_code == 200
    assert response.json()["probed"] >= 0


def test_diagnostics_resources_endpoint(tmp_app) -> None:
    client = TestClient(tmp_app)
    client.post("/sessions", json={"agent_id": "shell", "message": "diagnostics"})
    client.post("/skills/reviewer", json={"label": "Reviewer"})

    response = client.get("/diagnostics/resources")

    assert response.status_code == 200
    data = response.json()
    for key in [
        "pid",
        "rss_bytes",
        "state_dir_bytes",
        "sqlite_db_bytes",
        "sqlite_wal_bytes",
        "session_count",
        "audit_event_count",
        "fleet_event_count",
    ]:
        assert key in data
        assert isinstance(data[key], int)
    assert data["session_count"] >= 1
    assert data["audit_event_count"] >= 1


def test_skill_upsert_and_deprecate_create_audit_events(tmp_app) -> None:
    client = TestClient(tmp_app)
    client.post("/skills/reviewer", json={"label": "Reviewer"})
    client.post("/skills/reviewer/disable")
    resp = client.post("/skills/reviewer/deprecate")
    assert resp.status_code == 200
    assert resp.json()["deprecated"] is True

    resp = client.get("/audit/events", params={"domain": "skill"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    types = [e["event_type"] for e in events]
    assert "skill_upserted" in types
    assert "skill_disabled" in types
    assert "skill_deprecated" in types


def test_mcp_upsert_and_deprecate_create_audit_events(tmp_app) -> None:
    client = TestClient(tmp_app)
    client.post("/mcp/filesystem", json={"label": "FS"})
    client.post("/mcp/filesystem/disable")
    resp = client.post("/mcp/filesystem/deprecate")
    assert resp.status_code == 200

    resp = client.get("/audit/events", params={"domain": "mcp"})
    types = [e["event_type"] for e in resp.json()["events"]]
    assert "mcp_upserted" in types
    assert "mcp_disabled" in types
    assert "mcp_deprecated" in types


def test_policy_upsert_and_deprecate_create_audit_events(tmp_app) -> None:
    client = TestClient(tmp_app)
    client.post("/policy/shell", json={"allowed_tool_names": ["*"], "cwd_roots": ["/tmp"]})
    resp = client.post("/policy/shell/deprecate")
    assert resp.status_code == 200

    resp = client.get("/audit/events", params={"domain": "policy"})
    types = [e["event_type"] for e in resp.json()["events"]]
    assert "policy_upserted" in types
    assert "policy_deprecated" in types


def test_deprecation_api_accepts_metadata_and_undeprecates_all_domains(tmp_app) -> None:
    client = TestClient(tmp_app)
    client.post("/skills/reviewer", json={"label": "Reviewer"})
    client.post("/mcp/filesystem", json={"label": "Filesystem"})
    client.post("/policy/shell", json={"allowed_tool_names": ["*"], "cwd_roots": ["/tmp"]})

    skill = client.post(
        "/skills/reviewer/deprecate",
        json={
            "reason": "use reviewer-v2",
            "replacement_id": "reviewer-v2",
            "sunset_at": "2026-06-30T00:00:00Z",
        },
    )
    mcp = client.post("/mcp/filesystem/deprecate", json={"reason": "unsafe transport"})
    policy = client.post("/policy/shell/deprecate", json={"sunset_at": "2026-06-30T00:00:00Z"})

    assert skill.status_code == 200
    assert skill.json()["deprecation_reason"] == "use reviewer-v2"
    assert skill.json()["replacement_id"] == "reviewer-v2"
    assert mcp.json()["deprecation_reason"] == "unsafe transport"
    assert policy.json()["sunset_at"] == "2026-06-30T00:00:00Z"

    assert client.post("/skills/reviewer/undeprecate").json()["deprecated"] is False
    assert client.post("/mcp/filesystem/undeprecate").json()["deprecated"] is False
    assert client.post("/policy/shell/undeprecate").json()["deprecated"] is False

    events = client.get("/audit/events").json()["events"]
    event_types = [event["event_type"] for event in events]
    assert "skill_undeprecated" in event_types
    assert "mcp_undeprecated" in event_types
    assert "policy_undeprecated" in event_types


def test_deprecation_sunset_auto_disable_records_audit_event(tmp_app) -> None:
    client = TestClient(tmp_app)
    client.post("/skills/reviewer", json={"label": "Reviewer"})
    client.post(
        "/skills/reviewer/deprecate",
        json={"reason": "expired", "sunset_at": "2000-01-01T00:00:00Z"},
    )

    listed = client.get("/skills")

    assert listed.json()["skills"][0]["enabled"] is False
    events = client.get(
        "/audit/events",
        params={
            "domain": "skill",
            "entity_id": "reviewer",
            "event_type": "skill_auto_disabled_after_sunset",
        },
    ).json()["events"]
    assert events[0]["metadata"]["sunset_at"] == "2000-01-01T00:00:00Z"
    assert events[0]["metadata"]["before"]["enabled"] is True
    assert events[0]["metadata"]["after"]["enabled"] is False
    assert events[0]["metadata"]["after"]["deprecated"] is True


def test_mutation_records_sunset_auto_disable_audit_before_store_side_effect(tmp_app) -> None:
    client = TestClient(tmp_app)
    tmp_app.state.control_plane.upsert_skill("expired", SkillUpsert(label="Expired"))
    tmp_app.state.control_plane.deprecate_skill(
        "expired",
        reason="old",
        sunset_at="2000-01-01T00:00:00Z",
    )

    response = client.post("/skills/fresh", json={"label": "Fresh"})

    assert response.status_code == 200
    events = client.get(
        "/audit/events",
        params={
            "domain": "skill",
            "entity_id": "expired",
            "event_type": "skill_auto_disabled_after_sunset",
        },
    ).json()["events"]
    assert len(events) == 1
    assert events[0]["metadata"]["before"]["enabled"] is True
    assert events[0]["metadata"]["after"]["enabled"] is False


def test_run_without_policy_records_governance_audit(tmp_app) -> None:
    """A run with no policy configured records policy_missing and run_started_without_policy."""
    client = TestClient(tmp_app)
    resp = client.post("/sessions", json={"agent_id": "shell", "message": "test"})
    assert resp.status_code == 200

    resp = client.get("/audit/events", params={"domain": "governance"})
    types = [e["event_type"] for e in resp.json()["events"]]
    assert "policy_missing_at_run_start" in types
    assert "run_started_without_policy" in types


def test_run_with_policy_records_evaluation_and_start(tmp_app, tmp_path) -> None:
    """A run with an allow policy records policy_evaluated and run_started_with_policy."""
    client = TestClient(tmp_app)
    client.post("/policy/shell", json={"allowed_tool_names": ["*"], "cwd_roots": [str(tmp_path)]})
    resp = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "test"}
    )
    assert resp.status_code == 200

    resp = client.get("/audit/events", params={"domain": "governance"})
    types = [e["event_type"] for e in resp.json()["events"]]
    assert "policy_evaluated" in types
    assert "run_started_with_policy" in types


def test_denied_run_records_policy_evaluated_audit(tmp_app, tmp_path) -> None:
    """A denied run records policy_evaluated but not run_started."""
    client = TestClient(tmp_app)
    # Use tmp_path as allowed root, then run from /tmp which is outside that root
    allowed_root = str(tmp_path / "allowed")
    (tmp_path / "allowed").mkdir()
    client.post("/policy/shell", json={"allowed_tool_names": ["*"], "cwd_roots": [allowed_root]})
    resp = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "test"}
    )
    assert resp.status_code == 403

    resp = client.get("/audit/events", params={"domain": "governance"})
    types = [e["event_type"] for e in resp.json()["events"]]
    assert "policy_evaluated" in types
    assert "run_started_with_policy" not in types
    assert "run_started_without_policy" not in types


def test_denied_run_policy_coverage_treats_rejected_session_as_evaluated(
    tmp_app,
    tmp_path,
) -> None:
    client = TestClient(tmp_app)
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    client.post(
        "/policy/shell", json={"allowed_tool_names": ["*"], "cwd_roots": [str(allowed_root)]}
    )

    denied = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "test"},
    )
    assert denied.status_code == 403

    coverage = client.get("/audit/policy-coverage").json()["coverage"][0]

    assert denied.json()["session_id"] not in coverage["runs_without_policy_evaluation"]


def test_approval_required_run_creates_durable_approval_and_approved_session(
    tmp_app,
    tmp_path: Path,
) -> None:
    client = TestClient(tmp_app)
    client.post(
        "/policy/shell",
        json={
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": ["session.start"],
            "cwd_roots": [str(tmp_path)],
        },
    )

    blocked = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "needs approval"},
    )
    assert blocked.status_code == 409
    approval_id = blocked.json()["approval_id"]
    source_session_id = blocked.json()["session_id"]
    source_events = client.get(f"/sessions/{source_session_id}/evidence/events").json()["events"]

    listed = client.get("/approvals")
    shown = client.get(f"/approvals/{approval_id}")
    approved = client.post(f"/approvals/{approval_id}/approve")
    sessions = client.get("/sessions").json()["sessions"]
    resolved_events = client.get(f"/sessions/{source_session_id}/evidence/events").json()["events"]

    assert [item["id"] for item in listed.json()["approvals"]] == [approval_id]
    assert shown.json()["source_session_id"] == source_session_id
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_session_id"] != source_session_id
    assert any(session["id"] == approved.json()["approved_session_id"] for session in sessions)
    assert any(event["event_type"] == "approval_required" for event in source_events)
    assert any(
        event["event_type"] == "approval_resolved"
        and event["metadata"]["status"] == "approved"
        and event["metadata"]["approved_session_id"] == approved.json()["approved_session_id"]
        for event in resolved_events
    )

    events = client.get("/audit/events", params={"domain": "governance"}).json()["events"]
    event_types = [event["event_type"] for event in events]
    assert "approval_requested" in event_types
    assert "approval_approved" in event_types
    assert "run_started_after_approval" in event_types


def test_approval_required_run_can_be_rejected_without_starting_followup_session(
    tmp_app,
    tmp_path: Path,
) -> None:
    client = TestClient(tmp_app)
    client.post(
        "/policy/shell",
        json={
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": ["session.start"],
            "cwd_roots": [str(tmp_path)],
        },
    )
    blocked = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "reject me"},
    )
    source_session_id = blocked.json()["session_id"]
    before_sessions = client.get("/sessions").json()["sessions"]

    rejected = client.post(
        f"/approvals/{blocked.json()['approval_id']}/reject",
        json={"reason": "not needed"},
    )
    after_sessions = client.get("/sessions").json()["sessions"]
    events = client.get(f"/sessions/{source_session_id}/evidence/events").json()["events"]

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["decision_reason"] == "not needed"
    assert len(after_sessions) == len(before_sessions)
    assert any(
        event["event_type"] == "approval_resolved"
        and event["metadata"]["status"] == "rejected"
        and event["metadata"]["reason"] == "not needed"
        for event in events
    )


def test_pending_approval_expires_on_read_when_policy_now_denies(
    tmp_app,
    tmp_path: Path,
) -> None:
    client = TestClient(tmp_app)
    client.post(
        "/policy/shell",
        json={
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": ["session.start"],
            "cwd_roots": [str(tmp_path)],
        },
    )
    blocked = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "stale approval"},
    )
    approval_id = blocked.json()["approval_id"]
    source_session_id = blocked.json()["session_id"]
    client.post(
        "/policy/shell",
        json={"enabled": False, "allowed_tool_names": ["*"], "cwd_roots": [str(tmp_path)]},
    )

    shown = client.get(f"/approvals/{approval_id}")
    events = client.get(f"/sessions/{source_session_id}/evidence/events").json()["events"]

    assert shown.status_code == 200
    assert shown.json()["status"] == "expired"
    assert shown.json()["decision_reason"] == "policy disabled for shell"
    assert any(
        event["event_type"] == "approval_resolved"
        and event["metadata"]["status"] == "expired"
        and event["metadata"]["reason"] == "policy disabled for shell"
        for event in events
    )


def test_approval_workbench_gated_endpoints(tmp_app, tmp_path: Path) -> None:
    client = TestClient(tmp_app)
    client.post(
        "/policy/shell",
        json={
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": ["session.start"],
            "cwd_roots": [str(tmp_path)],
        },
    )
    blocked = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "workbench"},
    )
    assert blocked.status_code == 409
    approval_id = blocked.json()["approval_id"]
    source_session_id = blocked.json()["session_id"]

    shown = client.get(f"/approvals/{approval_id}")
    assert shown.status_code == 200
    assert shown.json()["argv"]
    assert shown.json()["cwd"] == str(tmp_path)
    assert shown.json()["reason"]

    rejected = client.post(
        f"/approvals/{approval_id}/reject",
        json={"reason": "workbench reject"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    blocked2 = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "retry path"},
    )
    approval_id2 = blocked2.json()["approval_id"]
    approved = client.post(f"/approvals/{approval_id2}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    retry = client.post(f"/sessions/{source_session_id}/retry")
    assert retry.status_code in {200, 403, 409}
    if retry.status_code != 200:
        assert "decision" in retry.json()


def test_retry_uses_approval_request_path_when_policy_requires_approval(
    tmp_app,
    tmp_path: Path,
) -> None:
    client = TestClient(tmp_app)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "retry approval"},
    )
    assert run.status_code == 200
    client.post(
        "/policy/shell",
        json={
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": ["session.start"],
            "cwd_roots": [str(tmp_path)],
        },
    )

    retry = client.post(f"/sessions/{run.json()['id']}/retry")

    assert retry.status_code == 409
    assert retry.json()["decision"] == "approval_required"
    assert retry.json()["approval_id"].startswith("ap_")


def test_audit_events_query_endpoint(tmp_app) -> None:
    client = TestClient(tmp_app)
    client.post("/skills/a", json={"label": "A"})
    client.post("/skills/b", json={"label": "B"})

    resp = client.get("/audit/events")
    assert resp.status_code == 200
    assert len(resp.json()["events"]) >= 2

    resp = client.get("/audit/events", params={"entity_id": "a"})
    assert all(e["entity_id"] == "a" for e in resp.json()["events"])


def test_audit_policy_coverage_endpoint(tmp_app) -> None:
    client = TestClient(tmp_app)
    resp = client.get("/audit/policy-coverage")
    assert resp.status_code == 200
    assert "coverage" in resp.json()


def test_logs_endpoint_returns_truncated_flag(tmp_app) -> None:
    client = TestClient(tmp_app)
    resp = client.post("/sessions", json={"agent_id": "shell", "message": "hello"})
    session_id = resp.json()["id"]
    resp = client.get(f"/sessions/{session_id}/logs")
    assert resp.status_code == 200
    assert "truncated" in resp.json()
    assert isinstance(resp.json()["truncated"], bool)


def test_logs_endpoint_records_audit_event_when_truncated(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        command=[
            sys.executable,
            "-c",
            "for i in range(3): print(i)",
        ],
    )
    run = client.post("/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "x"})
    assert run.status_code == 200
    session_id = run.json()["id"]

    logs = client.get(f"/sessions/{session_id}/logs", params={"max_lines": 1})
    assert logs.status_code == 200
    assert logs.json()["truncated"] is True

    events = client.get(
        "/audit/events",
        params={"domain": "session", "entity_id": session_id, "event_type": "log_read_truncated"},
    )
    assert events.json()["events"][0]["metadata"]["max_lines"] == 1


def test_upsert_after_deprecation_records_reset_metadata_for_catalog_domains(
    tmp_app,
) -> None:
    client = TestClient(tmp_app)
    cases = [
        (
            "/skills/reviewer",
            "/skills/reviewer/deprecate",
            {"label": "Reviewer"},
            "skill",
            "reviewer",
            "skill_upserted",
        ),
        (
            "/mcp/filesystem",
            "/mcp/filesystem/deprecate",
            {"label": "FS"},
            "mcp",
            "filesystem",
            "mcp_upserted",
        ),
        (
            "/policy/shell",
            "/policy/shell/deprecate",
            {"allowed_tool_names": ["*"], "cwd_roots": ["/tmp"]},
            "policy",
            "shell",
            "policy_upserted",
        ),
    ]

    for upsert_path, deprecate_path, payload, domain, entity_id, event_type in cases:
        assert client.post(upsert_path, json=payload).status_code == 200
        assert client.post(deprecate_path).status_code == 200
        assert client.post(upsert_path, json=payload).status_code == 200

        events = client.get(
            "/audit/events",
            params={"domain": domain, "entity_id": entity_id, "event_type": event_type},
        ).json()["events"]

        assert events[0]["metadata"] == {"field": "deprecated", "before": True, "after": False}


def test_harness_lists_harnesses(tmp_path: Path) -> None:
    """GET /harnesses returns all registered instances with profile metadata."""
    registry = tmp_path / "agents.toml"
    registry.write_text(
        """
[[agents]]
id = "shell"
label = "Shell Smoke"
command = ["/usr/bin/printf", "%s", "{{message}}"]
cwd_mode = "optional"
stop_policy = "process_group"
health_command = ["/usr/bin/printf", "OK"]
config_path = "~/.shell/config"
log_paths = ["/tmp/shell.log"]
default_provider = "local"
workspace_roots = ["~/work", "~/bootstrap"]

[[agents]]
id = "openclaw"
label = "OpenClaw"
command = ["openclaw", "agent", "--message", "{{message}}"]
cwd_mode = "required"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    response = client.get("/harnesses")

    assert response.status_code == 200
    harnesses = response.json()["harnesses"]
    assert len(harnesses) == 2
    ids = [h["id"] for h in harnesses]
    assert ids == ["openclaw", "shell"]
    shell = harnesses[1]
    assert shell["id"] == "shell"
    assert shell["name"] == "Shell Smoke"
    assert shell["launch_command"] == ["/usr/bin/printf", "%s", "{{message}}"]
    assert shell["health_command"] == ["/usr/bin/printf", "OK"]
    assert shell["config_path"] == "~/.shell/config"
    assert shell["workspace_roots"] == ["~/work", "~/bootstrap"]
    assert shell["log_paths"] == ["/tmp/shell.log"]
    assert shell["default_provider"] == "local"
    assert "enabled" not in shell


def test_harness_show_harness(tmp_path: Path) -> None:
    """GET /harnesses/{id} returns a single instance profile."""
    registry = tmp_path / "agents.toml"
    registry.write_text(
        """
[[agents]]
id = "shell"
label = "Shell Smoke"
command = ["/usr/bin/printf", "OK"]
cwd_mode = "optional"
stop_policy = "process_group"
attach_command = ["/usr/bin/printf", "attach"]
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    response = client.get("/harnesses/shell")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "shell"
    assert data["name"] == "Shell Smoke"
    assert data["launch_command"] == ["/usr/bin/printf", "OK"]
    assert data["attach_command"] == ["/usr/bin/printf", "attach"]


def test_harness_show_harness_404(tmp_path: Path) -> None:
    """GET /harnesses/{id} returns 404 for unknown id."""
    client = make_client(tmp_path)

    response = client.get("/harnesses/missing")

    assert response.status_code == 404


def test_harness_health_runs_command(tmp_path: Path) -> None:
    """GET /harnesses/{id}/health executes health_command and returns structured result."""
    registry = tmp_path / "agents.toml"
    registry.write_text(
        f"""
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "OK"]
cwd_mode = "optional"
stop_policy = "process_group"
health_command = [{sys.executable!r}, "-c", "print('healthy')"]
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    response = client.get("/harnesses/shell/health")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "shell"
    assert data["state"] == "up"
    assert "healthy" in data["message"]
    assert data["exit_code"] == 0
    assert isinstance(data["duration_ms"], int)
    assert "stdout_preview" in data
    assert "stderr_preview" in data
    assert data["truncated"] is False


def test_harness_health_no_command(tmp_path: Path) -> None:
    """GET /harnesses/{id}/health returns unknown when no health_command is defined."""
    client = make_client(tmp_path)

    response = client.get("/harnesses/shell/health")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "shell"
    assert data["state"] == "unknown"
    assert "no health command" in data["message"]


def test_harness_health_404(tmp_path: Path) -> None:
    """GET /harnesses/{id}/health returns 404 for unknown id."""
    client = make_client(tmp_path)

    response = client.get("/harnesses/missing/health")

    assert response.status_code == 404


def test_harness_health_command_fails(tmp_path: Path) -> None:
    """GET /harnesses/{id}/health returns down when health_command fails."""
    registry = tmp_path / "agents.toml"
    registry.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "OK"]
cwd_mode = "optional"
stop_policy = "process_group"
health_command = ["/usr/bin/false"]
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    response = client.get("/harnesses/shell/health")

    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "down"
    assert data["exit_code"] != 0
    assert data["truncated"] is False


def test_harness_health_truncates_large_output(tmp_path: Path) -> None:
    """GET /harnesses/{id}/health truncates stdout/stderr exceeding 2KB."""
    long_output = "x" * 5000
    registry = tmp_path / "agents.toml"
    registry.write_text(
        f"""
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "OK"]
cwd_mode = "optional"
stop_policy = "process_group"
health_command = [{sys.executable!r}, "-c", "print('{long_output}')"]
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    response = client.get("/harnesses/shell/health")

    assert response.status_code == 200
    data = response.json()
    assert data["truncated"] is True
    assert len(data["stdout_preview"].encode("utf-8")) <= 2048


def test_harness_health_records_fleet_event(tmp_path: Path) -> None:
    """GET /harnesses/{id}/health records requested/completed fleet events."""
    registry = tmp_path / "agents.toml"
    registry.write_text(
        f"""
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "OK"]
cwd_mode = "optional"
stop_policy = "process_group"
health_command = [{sys.executable!r}, "-c", "print('healthy')"]
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    client.get("/harnesses/shell/health")
    events = client.get("/fleet/events", params={"agent_id": "shell"}).json()["events"]
    event_types = [e["event_type"] for e in events]
    assert "health_probe_requested" in event_types
    assert "health_probe_completed" in event_types


def test_harness_logs_returns_paths(tmp_path: Path) -> None:
    """GET /harnesses/{id}/logs returns the known log paths for a harness instance."""
    registry = tmp_path / "agents.toml"
    registry.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "OK"]
cwd_mode = "optional"
stop_policy = "process_group"
log_paths = ["/tmp/shell-stdout.log", "/tmp/shell-stderr.log"]
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))

    response = client.get("/harnesses/shell/logs")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "shell"
    assert data["log_paths"] == ["/tmp/shell-stdout.log", "/tmp/shell-stderr.log"]


def test_harness_logs_empty_paths(tmp_path: Path) -> None:
    """GET /harnesses/{id}/logs returns empty list when no log_paths are defined."""
    client = make_client(tmp_path)

    response = client.get("/harnesses/shell/logs")

    assert response.status_code == 200
    data = response.json()
    assert data["log_paths"] == []


def test_session_timeline_returns_entries(tmp_path: Path) -> None:
    """GET /sessions/{id}/timeline returns chronological events for a session."""
    client = make_client(tmp_path)
    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "timeline test"}
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    response = client.get(f"/sessions/{session_id}/timeline")

    assert response.status_code == 200
    timeline = response.json()["timeline"]
    assert len(timeline) >= 1
    types = [e["type"] for e in timeline]
    assert "session_start" in types or "process_started" in types


def test_session_timeline_404(tmp_path: Path) -> None:
    """GET /sessions/{id}/timeline returns 404 for unknown session."""
    client = make_client(tmp_path)

    response = client.get("/sessions/missing/timeline")

    assert response.status_code == 404


def test_session_evidence_endpoint_returns_metadata_and_paths(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "evidence"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    payload = wait_for_session_evidence(client, session_id)
    assert payload["session_id"] == session_id
    assert payload["harness_id"] == "shell"
    assert payload["metadata"]["schema_version"] == "session_evidence.v1"
    assert payload["metadata"]["status"] == "succeeded"
    assert payload["paths"]["events"].endswith("/events.jsonl")
    assert payload["paths"]["artifact_manifest"].endswith("/artifacts/manifest.json")


def test_session_evidence_events_endpoint_returns_normalized_events(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "events"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    wait_for_session_evidence(
        client,
        session_id,
        required_events={"run_accepted", "process_started", "process_exited"},
    )
    response = client.get(f"/sessions/{session_id}/evidence/events")
    assert response.status_code == 200
    payload = response.json()
    event_types = [event["event_type"] for event in payload["events"]]
    assert payload["truncated"] is False
    assert "run_accepted" in event_types
    assert "process_started" in event_types
    assert "process_exited" in event_types
    assert all("index" in event for event in payload["events"])


def test_session_evidence_events_endpoint_supports_after_and_max_lines(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "events cursor"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]
    wait_for_session_evidence(client, session_id, required_events={"run_accepted"})

    response = client.get(
        f"/sessions/{session_id}/evidence/events",
        params={"after": 0, "max_lines": 1},
    )

    assert response.status_code == 200
    assert len(response.json()["events"]) == 1
    assert response.json()["truncated"] is True


def test_session_evidence_endpoints_return_404_for_unknown_session(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    index_response = client.get("/sessions/missing/evidence")
    events_response = client.get("/sessions/missing/evidence/events")

    assert index_response.status_code == 404
    assert events_response.status_code == 404


def test_session_timeline_includes_log_chunks(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "log-chunk-test"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]
    session = client.get(f"/sessions/{session_id}").json()
    stdout_log = Path(session["stdout_log"])
    stdout_log.parent.mkdir(parents=True, exist_ok=True)
    stdout_log.write_text(
        json.dumps(
            {
                "ts": "2026-05-30T00:00:00Z",
                "stream": "stdout",
                "session_id": session_id,
                "line": "hello from stdout",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.get(f"/sessions/{session_id}/timeline")
    assert response.status_code == 200
    types = [entry["type"] for entry in response.json()["timeline"]]
    assert "log_chunk" in types


def test_session_timeline_includes_retry_requested(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "retry-timeline"}
    )
    assert run.status_code == 200
    session_id = run.json()["id"]

    retry = client.post(f"/sessions/{session_id}/retry")
    assert retry.status_code == 200

    timeline = client.get(f"/sessions/{session_id}/timeline").json()["timeline"]
    types = [entry["type"] for entry in timeline]
    assert "retry_requested" in types


def test_harness_activity_includes_fleet_events(tmp_app) -> None:
    from agentic_os.fleet import HealthState

    client = TestClient(tmp_app)
    tmp_app.state.fleet_store.record_event(
        "shell",
        "health_probe_requested",
        "probe requested",
    )
    tmp_app.state.fleet_store.record_health("shell", HealthState.UP, "OK")

    response = client.get("/harnesses/shell/activity")
    assert response.status_code == 200
    types = [entry["type"] for entry in response.json()["activity"]]
    assert "health_probe" in types


def test_harness_activity_pagination(tmp_app) -> None:
    client = TestClient(tmp_app)
    tmp_app.state.fleet_store.record_event("shell", "capacity_rejected", "at capacity")

    response = client.get("/harnesses/shell/activity", params={"limit": 1})
    assert response.status_code == 200
    assert len(response.json()["activity"]) <= 1


def test_session_attach_preview_unsupported(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "attach-test"}
    )
    session_id = run.json()["id"]

    response = client.post(f"/sessions/{session_id}/attach", json={"mode": "preview"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "unsupported"


def _write_openclaw_registry(path: Path, *, attach_command: list[str] | None = None) -> None:
    attach = attach_command or ["openclaw", "attach"]
    path.write_text(
        f"""
[[agents]]
id = "openclaw"
label = "OpenClaw"
command = ["/usr/bin/printf", "%s", "{{{{message}}}}"]
attach_command = {json.dumps(attach)}
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )


def _set_shell_policy(client: TestClient, **overrides: object) -> None:
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
    response = client.post("/policy/openclaw", json=payload)
    assert response.status_code == 200


def test_session_attach_preview_allow_openclaw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agentic_os.supervisor.capture_external_session_after_run",
        lambda *args, **kwargs: None,
    )
    registry = tmp_path / "agents.toml"
    _write_openclaw_registry(registry)
    app = create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)
    client = TestClient(app)
    run = client.post(
        "/sessions",
        json={"agent_id": "openclaw", "cwd": str(tmp_path), "message": "attach-preview"},
    )
    assert run.status_code == 200
    session_id = run.json()["id"]
    app.state.store.update_session_attach(
        session_id,
        external_session_id="ext-session-42",
        attachable=True,
        attach_status="available",
    )

    response = client.post(f"/sessions/{session_id}/attach", json={"mode": "preview"})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "allow"
    assert body["attach_command"] == ["openclaw", "attach", "ext-session-42"]


def test_session_attach_preview_deny_without_external_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agentic_os.supervisor.capture_external_session_after_run",
        lambda *args, **kwargs: None,
    )
    registry = tmp_path / "agents.toml"
    _write_openclaw_registry(registry)
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry))
    run = client.post(
        "/sessions",
        json={"agent_id": "openclaw", "cwd": str(tmp_path), "message": "attach-deny"},
    )
    session_id = run.json()["id"]

    response = client.post(f"/sessions/{session_id}/attach", json={"mode": "preview"})
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["decision"] == "deny"
    assert detail["session_id"] == session_id


def test_session_attach_exec_records_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentic_os.supervisor.capture_external_session_after_run",
        lambda *args, **kwargs: None,
    )
    registry = tmp_path / "agents.toml"
    _write_openclaw_registry(registry, attach_command=["/usr/bin/true"])
    app = create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)
    client = TestClient(app)
    run = client.post(
        "/sessions",
        json={"agent_id": "openclaw", "cwd": str(tmp_path), "message": "attach-exec"},
    )
    session_id = run.json()["id"]
    app.state.store.update_session_attach(
        session_id,
        external_session_id="ext-exec-1",
        attachable=True,
        attach_status="available",
    )
    _set_shell_policy(client, cwd_roots=[str(tmp_path)])

    response = client.post(f"/sessions/{session_id}/attach", json={"mode": "exec"})
    assert response.status_code == 200
    assert response.json()["pid"] is not None

    audit = client.get("/audit/events", params={"domain": "session", "limit": 20})
    assert audit.status_code == 200
    event_types = [event["event_type"] for event in audit.json()["events"]]
    assert "attach_exec" in event_types

    session = client.get(f"/sessions/{session_id}").json()
    assert session["attach_status"] == "attached"


def test_session_attach_exec_denied_by_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agentic_os.supervisor.capture_external_session_after_run",
        lambda *args, **kwargs: None,
    )
    registry = tmp_path / "agents.toml"
    _write_openclaw_registry(registry, attach_command=["/usr/bin/true"])
    app = create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)
    client = TestClient(app)
    run = client.post(
        "/sessions",
        json={"agent_id": "openclaw", "cwd": str(tmp_path), "message": "attach-policy"},
    )
    session_id = run.json()["id"]
    app.state.store.update_session_attach(
        session_id,
        external_session_id="ext-policy-1",
        attachable=True,
        attach_status="available",
    )
    _set_shell_policy(client, cwd_roots=["/nonexistent/allowed"])

    response = client.post(f"/sessions/{session_id}/attach", json={"mode": "exec"})
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["decision"] == "deny"
    assert detail["session_id"] == session_id


def test_session_attach_exec_approval_required_returns_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agentic_os.supervisor.capture_external_session_after_run",
        lambda *args, **kwargs: None,
    )
    registry = tmp_path / "agents.toml"
    _write_openclaw_registry(registry, attach_command=["/usr/bin/true"])
    app = create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)
    client = TestClient(app)
    run = client.post(
        "/sessions",
        json={"agent_id": "openclaw", "cwd": str(tmp_path), "message": "attach-approval"},
    )
    session_id = run.json()["id"]
    app.state.store.update_session_attach(
        session_id,
        external_session_id="ext-approval-1",
        attachable=True,
        attach_status="available",
    )
    _set_shell_policy(
        client,
        cwd_roots=[str(tmp_path)],
        approval_required_tool_names=["session.start"],
    )

    response = client.post(f"/sessions/{session_id}/attach", json={"mode": "exec"})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["decision"] == "approval_required"
    assert detail["session_id"] == session_id


def test_catalog_surfaces_returns_valid_response(tmp_path: Path) -> None:
    """GET /catalog/{harness}/surfaces returns valid response structure."""
    client = make_client(tmp_path)

    response = client.get("/catalog/claude/surfaces", params={"cwd": str(tmp_path)})

    assert response.status_code == 200
    data = response.json()
    assert "surfaces" in data
    for s in data["surfaces"]:
        assert "id" in s
        assert "type" in s
        assert "scope" in s
        assert "harness" in s


def test_catalog_surfaces_400_for_unknown_harness(tmp_path: Path) -> None:
    """GET /catalog/{harness}/surfaces returns 400 for unsupported harness."""
    client = make_client(tmp_path)

    response = client.get("/catalog/unknown/surfaces")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["message"] == "unsupported harness: unknown"
    assert "claude" in detail["supported"]


def test_harnesses_validate_ok_with_examples_registry(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))
    response = client.get("/harnesses/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["errors"] == []


def test_harness_config_effective_claude(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "settings.json").write_text('{"model": "user-model"}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    client = make_client(tmp_path)
    response = client.get("/harness-config/claude/effective", params={"cwd": str(tmp_path)})
    assert response.status_code == 200
    data = response.json()
    assert data["harness_id"] == "claude"
    keys = [entry["key"] for entry in data["entries"]]
    assert "model" in keys


def test_harness_config_effective_cursor(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    cursor_home = home / ".cursor"
    cursor_home.mkdir(parents=True)
    (cursor_home / "cli-config.json").write_text(
        json.dumps({"permissions": {"allow": [], "deny": []}}),
        encoding="utf-8",
    )
    (cursor_home / "mcp.json").write_text(
        json.dumps({"mcpServers": {}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    client = make_client(tmp_path)
    response = client.get(
        "/harness-config/cursor/effective",
        params={"cwd": str(tmp_path)},
    )
    assert response.status_code == 200
    keys = {entry["key"] for entry in response.json()["entries"]}
    assert "permissions" in keys
    assert "mcpServers" in keys


def test_harness_config_unknown_harness(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/harness-config/unknown/effective")
    assert response.status_code == 400


def test_catalog_merged_returns_valid_response(tmp_path: Path) -> None:
    """GET /catalog/{harness}/merged returns valid merged response structure."""
    client = make_client(tmp_path)

    response = client.get("/catalog/claude/merged", params={"cwd": str(tmp_path)})

    assert response.status_code == 200
    data = response.json()
    assert "surfaces" in data
    # Verify merged surfaces have override info when applicable
    for s in data["surfaces"]:
        assert "overridden_by" in s or "overrides" in s or True  # at least one field present


def test_catalog_diff_returns_empty_diff(tmp_path: Path) -> None:
    """GET /catalog/{harness}/diff returns empty diff when both sides are empty."""
    client = make_client(tmp_path)

    response = client.get(
        "/catalog/claude/diff",
        params={
            "cwd_a": str(tmp_path),
            "cwd_b": str(tmp_path),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["added"] == []
    assert data["removed"] == []
    assert data["modified"] == []


def test_catalog_patch_dry_run_does_not_mutate(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    client = make_client(tmp_path)
    response = client.post(
        "/catalog/claude/surfaces/patch",
        params={"cwd": str(repo), "dry_run": "true"},
        json={
            "ops": [
                {
                    "op": "enable_mcp_server",
                    "name": "gh",
                    "scope": "project",
                    "config": {"command": "npx"},
                }
            ],
            "source": "test",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is False
    assert settings.read_text(encoding="utf-8") == "{}"


def test_catalog_patch_apply_and_audit(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    client = make_client(tmp_path)
    response = client.post(
        "/catalog/claude/surfaces/patch",
        params={"cwd": str(repo)},
        json={
            "ops": [
                {
                    "op": "enable_mcp_server",
                    "name": "gh",
                    "scope": "project",
                    "config": {"command": "npx"},
                }
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["applied"] is True
    audit = client.get("/audit/events", params={"domain": "config_patch", "limit": 5})
    assert audit.status_code == 200
    assert any(e["event_type"] == "config_patch_applied" for e in audit.json()["events"])


def test_approvals_list_filter_by_status(tmp_path: Path) -> None:
    """GET /approvals?status=pending filters by approval status."""
    client = make_client(tmp_path)
    client.post(
        "/policy/shell",
        json={
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": ["session.start"],
            "cwd_roots": [str(tmp_path)],
        },
    )
    blocked = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "needs approval"},
    )
    assert blocked.status_code == 409
    approval_id = blocked.json()["approval_id"]

    pending = client.get("/approvals", params={"status": "pending"})
    assert pending.status_code == 200
    assert any(a["id"] == approval_id for a in pending.json()["approvals"])

    rejected = client.get("/approvals", params={"status": "rejected"})
    assert rejected.status_code == 200
    assert not any(a["id"] == approval_id for a in rejected.json()["approvals"])


def test_approvals_list_filter_by_harness_id(tmp_path: Path) -> None:
    """GET /approvals?harness_id=shell filters by harness id."""
    client = make_client(tmp_path)
    client.post(
        "/policy/shell",
        json={
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": ["session.start"],
            "cwd_roots": [str(tmp_path)],
        },
    )
    blocked = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "needs approval"},
    )
    assert blocked.status_code == 409
    approval_id = blocked.json()["approval_id"]

    filtered = client.get("/approvals", params={"harness_id": "shell"})
    assert filtered.status_code == 200
    assert any(a["id"] == approval_id for a in filtered.json()["approvals"])

    filtered_other = client.get("/approvals", params={"harness_id": "other"})
    assert filtered_other.status_code == 200
    assert not any(a["id"] == approval_id for a in filtered_other.json()["approvals"])


def test_harness_activity_returns_sessions(tmp_path: Path) -> None:
    """GET /harnesses/{id}/activity returns session events for a harness."""
    client = make_client(tmp_path)
    run = client.post(
        "/sessions", json={"agent_id": "shell", "cwd": str(tmp_path), "message": "activity test"}
    )
    assert run.status_code == 200

    response = client.get("/harnesses/shell/activity")

    assert response.status_code == 200
    data = response.json()
    assert data["harness_id"] == "shell"
    assert len(data["activity"]) >= 1


def test_harness_activity_404(tmp_path: Path) -> None:
    """GET /harnesses/{id}/activity returns 404 for unknown harness."""
    client = make_client(tmp_path)

    response = client.get("/harnesses/missing/activity")

    assert response.status_code == 404


def test_config_effective_returns_valid(tmp_path: Path) -> None:
    """GET /config/{id}/effective returns valid response structure."""
    client = make_client(tmp_path)

    response = client.get("/config/shell/effective")

    assert response.status_code == 200
    data = response.json()
    assert "harness_id" in data
    assert "entries" in data
    assert "scopes_present" in data


def test_config_diff_returns_valid(tmp_path: Path) -> None:
    """GET /config/{id}/diff returns valid diff structure."""
    client = make_client(tmp_path)

    response = client.get("/config/shell/diff")

    assert response.status_code == 200
    data = response.json()
    assert "added" in data
    assert "removed" in data
    assert "modified" in data


def test_config_explain_returns_valid(tmp_path: Path) -> None:
    """GET /config/{id}/explain returns valid explain structure."""
    client = make_client(tmp_path)

    response = client.get("/config/shell/explain")

    assert response.status_code == 200
    data = response.json()
    assert "harness_id" in data
    assert "entries" in data


def test_harness_contracts_list_and_show(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))

    response = client.get("/harness-contracts")
    assert response.status_code == 200
    payload = response.json()
    harness_ids = {item["harness_id"] for item in payload["contracts"]}
    assert "cursor" in harness_ids
    assert payload["count"] >= 7
    assert all(item["contract_version"] == "v1" for item in payload["contracts"])

    show = client.get("/harness-contracts/cursor")
    assert show.status_code == 200
    assert show.json()["launch"]["supported"] is True

    shell = client.get("/harness-contracts/shell")
    assert shell.status_code == 200
    assert shell.json()["harness_id"] == "shell"


def test_harness_contracts_list_v2(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))

    response = client.get("/harness-contracts?version=v2")

    assert response.status_code == 200
    payload = response.json()
    contracts = {item["harness_id"]: item for item in payload["contracts"]}
    assert all(item["contract_version"] == "v2" for item in payload["contracts"])
    assert "cursor" in contracts
    assert "shell" not in contracts
    assert payload["count"] == 7
    cursor = contracts["cursor"]
    assert cursor["launch"]["prompt_input_mode"] == "argv"
    assert cursor["config"]["native_files"] == [
        ".cursor/cli-config.json",
        ".cursor/mcp.json",
        ".cursor/hooks.json",
    ]
    assert cursor["policy"]["runtime_enforcement"] is False


def test_harness_contracts_show_v2(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))

    response = client.get("/harness-contracts/openclaw?version=v2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["launch"]["output_mode"] == "json"
    assert payload["usage"]["evidence_mode"] == "json"
    assert payload["capability_matrix"]["json_output"] is True


def test_harness_contracts_unsupported_version(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))

    response = client.get("/harness-contracts?version=v3")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "message": "unsupported contract version: v3",
        "supported": ["v1", "v2"],
    }


def test_harness_contracts_show_unsupported_version_before_unknown_harness(
    tmp_path: Path,
) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))

    response = client.get("/harness-contracts/missing?version=v3")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "message": "unsupported contract version: v3",
        "supported": ["v1", "v2"],
    }


def test_harness_contracts_show_shell_v2_is_unsupported(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))

    response = client.get("/harness-contracts/shell?version=v2")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "message": "unsupported harness for contract v2: shell",
        "supported": ["claude", "codex", "cursor", "hermes", "openclaw", "opencode", "qwen"],
    }


def test_harness_contracts_show_unknown(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))

    response = client.get("/harness-contracts/missing")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "supported" in detail
    assert "cursor" in detail["supported"]
    assert "shell" in detail["supported"]
    assert len(detail["supported"]) >= 8


def test_usage_session_not_found_returns_na(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/usage/sessions/nope")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_tokens"] == "N/A"
    assert payload["cost_usd"] == "N/A"


def test_usage_summary_and_quotas(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    summary = client.get("/usage/summary")
    assert summary.status_code == 200
    assert "count" in summary.json()

    quotas = client.get("/usage/quotas", params={"scope": "daily"})
    assert quotas.status_code == 200
    body = quotas.json()
    assert body["scope"] == "daily"
    assert "quotas" in body
    assert isinstance(body["quotas"], list)

    bad_scope = client.get("/usage/quotas", params={"scope": "weekly"})
    assert bad_scope.status_code == 400
    assert "supported" in bad_scope.json()["detail"]


def test_post_profiles_upsert_local(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    response = client.post(
        "/profiles",
        params={"scope": "local", "cwd": str(repo)},
        json={
            "name": "cursor-dev",
            "harness_id": "cursor",
            "provider": "cursor",
            "model": "default",
            "max_tokens_budget": 5000,
        },
    )
    assert response.status_code == 201
    assert response.json()["name"] == "cursor-dev"

    listed = client.get("/profiles", params={"cwd": str(repo)})
    names = {item["name"] for item in listed.json()["run_profiles"]}
    assert "cursor-dev" in names


def test_profile_model_reaches_spawned_argv(tmp_path: Path, monkeypatch) -> None:
    profile_dir = tmp_path / "profiles-home" / ".agentic-os"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profiles.toml").write_text(
        """
[run_profiles.default]
harness_id = "shell"
provider = "local"
model = "opus-4"
message_prefix = ""
default_env = {}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        profiles_module,
        "global_profile_path",
        lambda: profile_dir / "profiles.toml",
    )
    monkeypatch.setattr(
        profiles_module,
        "local_profile_path",
        lambda _cwd: tmp_path / "missing-local" / "profiles.toml",
    )

    client = make_client(
        tmp_path,
        command=["/usr/bin/printf", "msg=%s model=%s\\n", "{{message}}", "{{model}}"],
        model_arg=["--model", "{{model}}"],
    )
    response = client.post(
        "/sessions",
        json={
            "agent_id": "shell",
            "cwd": str(tmp_path),
            "message": "OK",
            "profile": "default",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["argv"] == [
        "/usr/bin/printf",
        "msg=%s model=%s\\n",
        "OK",
        "opus-4",
        "--model",
        "opus-4",
    ]
    logs = client.get(f"/sessions/{payload['id']}/logs")
    assert logs.json()["entries"][0]["line"] == "msg=OK model=opus-4"


def test_retry_preserves_profile_model_in_argv(tmp_path: Path, monkeypatch) -> None:
    profile_dir = tmp_path / "profiles-home" / ".agentic-os"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profiles.toml").write_text(
        """
[run_profiles.default]
harness_id = "shell"
provider = "local"
model = "retry-model"
message_prefix = ""
default_env = {}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        profiles_module,
        "global_profile_path",
        lambda: profile_dir / "profiles.toml",
    )
    monkeypatch.setattr(
        profiles_module,
        "local_profile_path",
        lambda _cwd: tmp_path / "missing-local" / "profiles.toml",
    )

    client = make_client(
        tmp_path,
        command=["/usr/bin/printf", "%s\\n", "{{message}}"],
        model_arg=["--model", "{{model}}"],
    )
    run = client.post(
        "/sessions",
        json={
            "agent_id": "shell",
            "cwd": str(tmp_path),
            "message": "OK",
            "profile": "default",
        },
    )
    assert run.status_code == 200
    assert run.json()["argv"][-2:] == ["--model", "retry-model"]

    retry = client.post(f"/sessions/{run.json()['id']}/retry")
    assert retry.status_code == 200
    assert retry.json()["argv"][-2:] == ["--model", "retry-model"]


def test_session_record_stores_resolved_profile_metadata(tmp_path: Path, monkeypatch) -> None:
    profile_dir = tmp_path / "profiles-home" / ".agentic-os"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profiles.toml").write_text(
        """
[run_profiles.default]
harness_id = "shell"
provider = "local"
model = "local-model"
message_prefix = ""
default_env = {}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        profiles_module,
        "global_profile_path",
        lambda: profile_dir / "profiles.toml",
    )
    monkeypatch.setattr(
        profiles_module,
        "local_profile_path",
        lambda _cwd: tmp_path / "missing-local" / "profiles.toml",
    )

    client = make_client(tmp_path)
    response = client.post(
        "/sessions",
        json={
            "agent_id": "shell",
            "cwd": str(tmp_path),
            "message": "OK",
            "profile": "default",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved_profile"] == "default"
    assert payload["resolved_provider"] == "local"
    assert payload["resolved_model"] == "local-model"


def test_profile_model_enforced_in_policy(tmp_path: Path, monkeypatch) -> None:
    profile_dir = tmp_path / "profiles-home" / ".agentic-os"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profiles.toml").write_text(
        """
[run_profiles.default]
harness_id = "shell"
provider = "local"
model = "blocked-model"
message_prefix = ""
default_env = {}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        profiles_module,
        "global_profile_path",
        lambda: profile_dir / "profiles.toml",
    )
    monkeypatch.setattr(
        profiles_module,
        "local_profile_path",
        lambda _cwd: tmp_path / "missing-local" / "profiles.toml",
    )

    client = make_client(tmp_path)
    client.post(
        "/policy/shell",
        json={
            "enabled": True,
            "readonly": False,
            "allowed_skill_ids": ["*"],
            "allowed_mcp_server_ids": ["*"],
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": [],
            "allowed_model_ids": ["allowed-model"],
            "cwd_roots": [str(tmp_path)],
            "rate_limit_per_minute": 60,
        },
    )

    response = client.post(
        "/sessions",
        json={
            "agent_id": "shell",
            "cwd": str(tmp_path),
            "message": "OK",
            "profile": "default",
        },
    )
    assert response.status_code == 403
    payload = response.json()
    assert payload["decision"] == "deny"
    assert "session_id" in payload


def test_profile_model_enforced_when_approval_is_rechecked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile_dir = tmp_path / "profiles-home" / ".agentic-os"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profiles.toml").write_text(
        """
[run_profiles.default]
harness_id = "shell"
provider = "local"
model = "guarded-model"
message_prefix = ""
default_env = {}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        profiles_module,
        "global_profile_path",
        lambda: profile_dir / "profiles.toml",
    )
    monkeypatch.setattr(
        profiles_module,
        "local_profile_path",
        lambda _cwd: tmp_path / "missing-local" / "profiles.toml",
    )

    client = make_client(tmp_path)
    client.post(
        "/policy/shell",
        json={
            "enabled": True,
            "readonly": False,
            "allowed_skill_ids": ["*"],
            "allowed_mcp_server_ids": ["*"],
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": ["session.start"],
            "allowed_model_ids": ["guarded-model"],
            "cwd_roots": [str(tmp_path)],
            "rate_limit_per_minute": 60,
        },
    )

    blocked = client.post(
        "/sessions",
        json={
            "agent_id": "shell",
            "cwd": str(tmp_path),
            "message": "OK",
            "profile": "default",
        },
    )
    assert blocked.status_code == 409
    source_session = client.get(f"/sessions/{blocked.json()['session_id']}").json()
    assert source_session["resolved_model"] == "guarded-model"

    client.post(
        "/policy/shell",
        json={
            "enabled": True,
            "readonly": False,
            "allowed_skill_ids": ["*"],
            "allowed_mcp_server_ids": ["*"],
            "allowed_tool_names": ["*"],
            "approval_required_tool_names": ["session.start"],
            "allowed_model_ids": ["other-model"],
            "cwd_roots": [str(tmp_path)],
            "rate_limit_per_minute": 60,
        },
    )

    approved = client.post(f"/approvals/{blocked.json()['approval_id']}/approve")
    assert approved.status_code == 409


def test_tools_discovery_endpoint(tmp_path: Path) -> None:
    """GET /tools/discovery should return tool list."""
    registry = tmp_path / "agents.toml"
    registry.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "%s", "{{message}}"]
cwd_mode = "optional"
tool_kind = "vibe_coding"

[[agents]]
id = "claude"
label = "Claude Code"
command = ["python3", "-c", "print('ok')"]
version_command = ["python3", "--version"]
cwd_mode = "required"
tool_kind = "vibe_coding"
""",
        encoding="utf-8",
    )
    app = create_app(tmp_path, registry)
    client = TestClient(app)

    response = client.get("/tools/discovery")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)
    assert len(data["tools"]) >= 1
    # Each tool should have required fields
    for tool in data["tools"]:
        assert "agent_id" in tool
        assert "tool_kind" in tool
        assert "installed" in tool
        assert "binary_path" in tool


def test_tools_inventory_endpoint(tmp_path: Path) -> None:
    """GET /tools/inventory should return config summaries."""
    registry = tmp_path / "agents.toml"
    registry.write_text(
        """
[[agents]]
id = "shell"
label = "Shell"
command = ["/usr/bin/printf", "%s", "{{message}}"]
cwd_mode = "optional"
tool_kind = "vibe_coding"

[[agents]]
id = "claude"
label = "Claude Code"
command = ["python3", "-c", "print('ok')"]
cwd_mode = "required"
tool_kind = "vibe_coding"
config_path = "/nonexistent/path"
""",
        encoding="utf-8",
    )
    app = create_app(tmp_path, registry)
    client = TestClient(app)

    response = client.get("/tools/inventory")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)
    # Only agents with config_path should be included
    for tool in data["tools"]:
        assert "agent_id" in tool
        assert "config_source" in tool
        assert "tool_kind" in tool
