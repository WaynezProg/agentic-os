from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from agentic_os import cli
from agentic_os.client import AgenticClient


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def list_agents(self) -> dict[str, object]:
        self.calls.append(("list_agents", (), {}))
        return {"agents": [{"id": "shell", "label": "Shell", "enabled": True}]}

    def show_agent(self, agent_id: str) -> dict[str, object]:
        self.calls.append(("show_agent", (agent_id,), {}))
        return {"id": agent_id, "label": "Shell", "enabled": True}

    def run_session(self, agent_id: str, cwd: str | None, message: str) -> dict[str, object]:
        self.calls.append(("run_session", (agent_id, cwd, message), {}))
        return {"id": "s_1", "agent_id": agent_id, "cwd": cwd, "status": "succeeded"}

    def list_sessions(self) -> dict[str, object]:
        self.calls.append(("list_sessions", (), {}))
        return {"sessions": [{"id": "s_1", "agent_id": "shell", "status": "succeeded"}]}

    def show_session(self, session_id: str) -> dict[str, object]:
        self.calls.append(("show_session", (session_id,), {}))
        return {"id": session_id, "agent_id": "shell", "status": "succeeded"}

    def get_logs(
        self,
        session_id: str,
        stream: str | None = None,
        after: int = 0,
    ) -> dict[str, object]:
        self.calls.append(("get_logs", (session_id, stream, after), {}))
        return {
            "entries": [
                {"stream": "stdout", "line": "OK", "index": after + 1},
            ]
        }

    def stop_session(self, session_id: str) -> dict[str, object]:
        self.calls.append(("stop_session", (session_id,), {}))
        return {"id": session_id, "status": "stopped"}

    def retry_session(self, session_id: str) -> dict[str, object]:
        self.calls.append(("retry_session", (session_id,), {}))
        return {"id": "s_2", "agent_id": "shell", "status": "queued"}

    def summarize_session(self, session_id: str) -> dict[str, object]:
        self.calls.append(("summarize_session", (session_id,), {}))
        return {
            "id": "sum_1",
            "session_id": session_id,
            "agent_id": "shell",
            "status": "succeeded",
            "one_liner": "Remember outcome",
        }

    def show_session_summary(self, session_id: str) -> dict[str, object]:
        self.calls.append(("show_session_summary", (session_id,), {}))
        return {
            "id": "sum_1",
            "session_id": session_id,
            "one_liner": "Remember outcome",
        }

    def create_memory_review(self, session_id: str) -> dict[str, object]:
        self.calls.append(("create_memory_review", (session_id,), {}))
        return {
            "id": "mri_1",
            "session_id": session_id,
            "status": "pending",
            "title": "Remember outcome",
        }

    def list_memory_review(self) -> dict[str, object]:
        self.calls.append(("list_memory_review", (), {}))
        return {
            "items": [
                {
                    "id": "mri_1",
                    "session_id": "s_1",
                    "status": "pending",
                    "title": "Remember outcome",
                }
            ]
        }

    def approve_memory_review(self, item_id: str) -> dict[str, object]:
        self.calls.append(("approve_memory_review", (item_id,), {}))
        return {
            "id": "mem_1",
            "review_item_id": item_id,
            "session_id": "s_1",
            "kind": "project_memory",
            "title": "Remember outcome",
        }

    def reject_memory_review(self, item_id: str) -> dict[str, object]:
        self.calls.append(("reject_memory_review", (item_id,), {}))
        return {
            "id": item_id,
            "session_id": "s_1",
            "status": "rejected",
            "title": "Remember outcome",
        }

    def list_memories(self) -> dict[str, object]:
        self.calls.append(("list_memories", (), {}))
        return {
            "memories": [
                {
                    "id": "mem_1",
                    "session_id": "s_1",
                    "kind": "project_memory",
                    "title": "Remember outcome",
                }
            ]
        }

    def search_memories(self, query: str) -> dict[str, object]:
        self.calls.append(("search_memories", (query,), {}))
        return {
            "memories": [
                {
                    "id": "mem_2",
                    "session_id": "s_2",
                    "kind": "project_memory",
                    "title": f"Match {query}",
                }
            ]
        }


def install_fake_client(monkeypatch: Any, fake: FakeClient) -> None:
    monkeypatch.setattr(cli, "make_client", lambda api: fake)


def test_agents_list_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["agents", "list"])

    assert result.exit_code == 0
    assert result.output == "shell\tShell\tenabled\n"
    assert fake.calls == [("list_agents", (), {})]


def test_agents_show_prints_agent_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["agents", "show", "shell"])

    assert result.exit_code == 0
    assert '"id": "shell"' in result.output
    assert fake.calls == [("show_agent", ("shell",), {})]


def test_run_resolves_cwd_and_prints_tab_separated_row(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    cwd = tmp_path / "nested"
    cwd.mkdir()

    result = CliRunner().invoke(
        cli.app,
        ["run", "shell", "--cwd", str(cwd / "."), "--message", "OK"],
    )

    assert result.exit_code == 0
    assert result.output == "s_1\tshell\tsucceeded\n"
    assert fake.calls == [("run_session", ("shell", str(cwd.resolve()), "OK"), {})]


def test_run_omits_cwd_when_not_provided(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["run", "shell", "--message", "OK"])

    assert result.exit_code == 0
    assert fake.calls == [("run_session", ("shell", None, "OK"), {})]


def test_sessions_list_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["sessions", "list"])

    assert result.exit_code == 0
    assert result.output == "s_1\tshell\tsucceeded\n"
    assert fake.calls == [("list_sessions", (), {})]


def test_sessions_show_prints_session_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["sessions", "show", "s_1"])

    assert result.exit_code == 0
    assert '"id": "s_1"' in result.output
    assert fake.calls == [("show_session", ("s_1",), {})]


def test_logs_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["logs", "s_1"])

    assert result.exit_code == 0
    assert result.output == "stdout\tOK\n"
    assert fake.calls == [("get_logs", ("s_1", None, 0), {})]


def test_stop_prints_tab_separated_row(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["stop", "s_1"])

    assert result.exit_code == 0
    assert result.output == "s_1\tstopped\n"
    assert fake.calls == [("stop_session", ("s_1",), {})]


def test_retry_prints_tab_separated_row(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["retry", "s_1"])

    assert result.exit_code == 0
    assert result.output == "s_2\tshell\tqueued\n"
    assert fake.calls == [("retry_session", ("s_1",), {})]


def test_memory_summarize_prints_summary_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["memory", "summarize", "s_1"])

    assert result.exit_code == 0
    assert '"session_id": "s_1"' in result.output
    assert '"one_liner": "Remember outcome"' in result.output
    assert fake.calls == [("summarize_session", ("s_1",), {})]


def test_memory_review_create_prints_review_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["memory", "review", "create", "s_1"])

    assert result.exit_code == 0
    assert '"id": "mri_1"' in result.output
    assert '"status": "pending"' in result.output
    assert fake.calls == [("create_memory_review", ("s_1",), {})]


def test_memory_review_list_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["memory", "review", "list"])

    assert result.exit_code == 0
    assert result.output == "mri_1\ts_1\tpending\tRemember outcome\n"
    assert fake.calls == [("list_memory_review", (), {})]


def test_memory_approve_prints_memory_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["memory", "approve", "mri_1"])

    assert result.exit_code == 0
    assert '"review_item_id": "mri_1"' in result.output
    assert '"kind": "project_memory"' in result.output
    assert fake.calls == [("approve_memory_review", ("mri_1",), {})]


def test_memory_reject_prints_review_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["memory", "reject", "mri_1"])

    assert result.exit_code == 0
    assert '"id": "mri_1"' in result.output
    assert '"status": "rejected"' in result.output
    assert fake.calls == [("reject_memory_review", ("mri_1",), {})]


def test_memory_list_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["memory", "list"])

    assert result.exit_code == 0
    assert result.output == "mem_1\ts_1\tproject_memory\tRemember outcome\n"
    assert fake.calls == [("list_memories", (), {})]


def test_memory_search_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["memory", "search", "branch fix"])

    assert result.exit_code == 0
    assert result.output == "mem_2\ts_2\tproject_memory\tMatch branch fix\n"
    assert fake.calls == [("search_memories", ("branch fix",), {})]


def test_make_client_uses_default_env_and_explicit_api(monkeypatch: Any) -> None:
    monkeypatch.delenv("AGENTIC_OS_API", raising=False)
    assert cli.make_client(None).base_url == "http://127.0.0.1:8767"

    monkeypatch.setenv("AGENTIC_OS_API", "http://env.example:9000/")
    assert cli.make_client(None).base_url == "http://env.example:9000"
    assert cli.make_client("http://explicit.example:9001/").base_url == "http://explicit.example:9001"


class RecordingHttpxClient:
    requests: list[dict[str, Any]] = []

    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def __enter__(self) -> "RecordingHttpxClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def get(self, path: str, params: dict[str, object] | None = None) -> "FakeResponse":
        self.requests.append(
            {"method": "GET", "base_url": self.base_url, "path": path, "params": params}
        )
        return FakeResponse({"entries": []})

    def post(self, path: str, json: dict[str, object]) -> "FakeResponse":
        self.requests.append(
            {"method": "POST", "base_url": self.base_url, "path": path, "json": json}
        )
        return FakeResponse({"id": "s_1"})


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


def test_client_get_logs_builds_after_and_stream_query(monkeypatch: Any) -> None:
    RecordingHttpxClient.requests = []
    monkeypatch.setattr("agentic_os.client.httpx.Client", RecordingHttpxClient)

    client = AgenticClient("http://api.example/")
    assert client.get_logs("s_1", after=7) == {"entries": []}
    assert client.get_logs("s_1", stream="stderr", after=8) == {"entries": []}

    assert RecordingHttpxClient.requests == [
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/sessions/s_1/logs",
            "params": {"after": 7},
        },
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/sessions/s_1/logs",
            "params": {"after": 8, "stream": "stderr"},
        },
    ]


def test_client_memory_methods_build_expected_requests(monkeypatch: Any) -> None:
    RecordingHttpxClient.requests = []
    monkeypatch.setattr("agentic_os.client.httpx.Client", RecordingHttpxClient)

    client = AgenticClient("http://api.example/")
    client.summarize_session("s_1")
    client.show_session_summary("s_1")
    client.create_memory_review("s_1")
    client.list_memory_review()
    client.approve_memory_review("mri_1")
    client.reject_memory_review("mri_2")
    client.list_memories()
    client.search_memories("branch/fix? ok")
    client.list_skills()
    client.list_mcp_servers()

    assert RecordingHttpxClient.requests == [
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/sessions/s_1/memory/summary",
            "json": {},
        },
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/sessions/s_1/memory/summary",
            "params": None,
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/sessions/s_1/memory/review",
            "json": {},
        },
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/memory/review",
            "params": None,
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/memory/review/mri_1/approve",
            "json": {},
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/memory/review/mri_2/reject",
            "json": {},
        },
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/memory",
            "params": None,
        },
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/memory/search",
            "params": {"q": "branch/fix? ok"},
        },
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/skills",
            "params": None,
        },
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/mcp",
            "params": None,
        },
    ]


@pytest.mark.parametrize(
    "unsafe_id",
    ["", "id/with/slash", "id?query=1", "id#fragment", "id%2Flogs"],
)
def test_client_rejects_unsafe_path_ids_before_http_request(
    monkeypatch: Any,
    unsafe_id: str,
) -> None:
    def fail_if_http_client_is_created(*args: object, **kwargs: object) -> RecordingHttpxClient:
        raise AssertionError("httpx.Client should not be called for unsafe IDs")

    monkeypatch.setattr("agentic_os.client.httpx.Client", fail_if_http_client_is_created)
    client = AgenticClient("http://api.example/")

    calls = [
        lambda: client.show_agent(unsafe_id),
        lambda: client.show_session(unsafe_id),
        lambda: client.get_logs(unsafe_id),
        lambda: client.stop_session(unsafe_id),
        lambda: client.retry_session(unsafe_id),
        lambda: client.summarize_session(unsafe_id),
        lambda: client.show_session_summary(unsafe_id),
        lambda: client.create_memory_review(unsafe_id),
        lambda: client.approve_memory_review(unsafe_id),
        lambda: client.reject_memory_review(unsafe_id),
    ]

    for call in calls:
        with pytest.raises(ValueError, match="unsafe path id"):
            call()


def test_client_allows_current_path_id_characters(monkeypatch: Any) -> None:
    RecordingHttpxClient.requests = []
    monkeypatch.setattr("agentic_os.client.httpx.Client", RecordingHttpxClient)

    client = AgenticClient("http://api.example/")
    client.show_agent("agent.v1:local-run_1")
    client.show_session("s_123")

    assert [request["path"] for request in RecordingHttpxClient.requests] == [
        "/agents/agent.v1:local-run_1",
        "/sessions/s_123",
    ]


def test_client_raises_for_http_errors(monkeypatch: Any) -> None:
    class ErrorResponse(FakeResponse):
        def raise_for_status(self) -> None:
            request = httpx.Request("GET", "http://api.example/agents/missing")
            response = httpx.Response(404, json={"detail": "unknown agent"}, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

    class ErrorHttpxClient(RecordingHttpxClient):
        def get(self, path: str, params: dict[str, object] | None = None) -> FakeResponse:
            return ErrorResponse({})

    monkeypatch.setattr("agentic_os.client.httpx.Client", ErrorHttpxClient)

    with pytest.raises(httpx.HTTPStatusError) as error:
        AgenticClient("http://api.example").show_agent("missing")

    assert error.value.response.status_code == 404
    assert error.value.response.json() == {"detail": "unknown agent"}


@pytest.mark.parametrize(
    ("status_code", "detail"),
    [
        (400, "bad request"),
        (404, "missing session"),
        (409, "already terminal"),
        (500, "daemon exploded"),
    ],
)
def test_cli_http_errors_exit_nonzero_without_traceback(
    monkeypatch: Any,
    status_code: int,
    detail: str,
) -> None:
    class ErrorClient(FakeClient):
        def list_agents(self) -> dict[str, object]:
            request = httpx.Request("GET", "http://api.example/agents")
            response = httpx.Response(status_code, json={"detail": detail}, request=request)
            raise httpx.HTTPStatusError("server error", request=request, response=response)

    install_fake_client(monkeypatch, ErrorClient())

    result = CliRunner().invoke(cli.app, ["agents", "list"])

    assert result.exit_code != 0
    assert str(status_code) in result.output
    assert detail in result.output
    assert "Traceback" not in result.output


def test_cli_request_errors_exit_nonzero_without_traceback(monkeypatch: Any) -> None:
    class ErrorClient(FakeClient):
        def list_agents(self) -> dict[str, object]:
            request = httpx.Request("GET", "http://api.example/agents")
            raise httpx.ConnectError("connection refused", request=request)

    install_fake_client(monkeypatch, ErrorClient())

    result = CliRunner().invoke(cli.app, ["agents", "list"])

    assert result.exit_code != 0
    assert "Request failed" in result.output
    assert "connection refused" in result.output
    assert "Traceback" not in result.output


def test_cli_local_validation_errors_exit_nonzero_without_traceback(monkeypatch: Any) -> None:
    def fail_if_http_client_is_created(*args: object, **kwargs: object) -> RecordingHttpxClient:
        raise AssertionError("httpx.Client should not be called for unsafe IDs")

    monkeypatch.setattr("agentic_os.client.httpx.Client", fail_if_http_client_is_created)

    result = CliRunner().invoke(cli.app, ["sessions", "show", "s_1%2Flogs"])

    assert result.exit_code != 0
    assert "unsafe path id" in result.output
    assert "Traceback" not in result.output


def test_logs_follow_advances_cursor_and_does_not_duplicate_lines(monkeypatch: Any) -> None:
    class StopFollow(Exception):
        pass

    class FollowClient(FakeClient):
        def get_logs(
            self,
            session_id: str,
            stream: str | None = None,
            after: int = 0,
        ) -> dict[str, object]:
            self.calls.append(("get_logs", (session_id, stream, after), {}))
            if len(self.calls) == 1:
                return {
                    "entries": [
                        {"stream": "stderr", "line": "first", "index": 1},
                        {"stream": "stderr", "line": "second", "index": 3},
                    ]
                }
            if len(self.calls) == 2:
                return {"entries": [{"stream": "stderr", "line": "third", "index": 4}]}
            raise StopFollow

    fake = FollowClient()
    install_fake_client(monkeypatch, fake)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    result = CliRunner().invoke(cli.app, ["logs", "s_1", "--follow", "--stream", "stderr"])

    assert isinstance(result.exception, StopFollow)
    assert result.output == "stderr\tfirst\nstderr\tsecond\nstderr\tthird\n"
    assert fake.calls == [
        ("get_logs", ("s_1", "stderr", 0), {}),
        ("get_logs", ("s_1", "stderr", 3), {}),
        ("get_logs", ("s_1", "stderr", 4), {}),
    ]


def test_help_commands_import_successfully() -> None:
    runner = CliRunner()

    assert runner.invoke(cli.app, ["--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["agents", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["sessions", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["memory", "--help"]).exit_code == 0
