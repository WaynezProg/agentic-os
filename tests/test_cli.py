from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
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

    try:
        AgenticClient("http://api.example").show_agent("missing")
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 404
        assert exc.response.json() == {"detail": "unknown agent"}
    else:
        raise AssertionError("expected HTTPStatusError")


def test_cli_http_errors_exit_nonzero_without_traceback(monkeypatch: Any) -> None:
    class ErrorClient(FakeClient):
        def list_agents(self) -> dict[str, object]:
            request = httpx.Request("GET", "http://api.example/agents")
            response = httpx.Response(500, json={"detail": "daemon exploded"}, request=request)
            raise httpx.HTTPStatusError("server error", request=request, response=response)

    install_fake_client(monkeypatch, ErrorClient())

    result = CliRunner().invoke(cli.app, ["agents", "list"])

    assert result.exit_code != 0
    assert "500" in result.output
    assert "daemon exploded" in result.output
    assert "Traceback" not in result.output


def test_help_commands_import_successfully() -> None:
    runner = CliRunner()

    assert runner.invoke(cli.app, ["--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["agents", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["sessions", "--help"]).exit_code == 0
