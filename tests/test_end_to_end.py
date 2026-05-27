from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import uvicorn
from typer.testing import CliRunner, Result

from agentic_os import cli
from agentic_os.api import create_app


def write_smoke_registry(path: Path) -> None:
    shell_command = ["/usr/bin/printf", "%s", "{{message}}"]
    sleeper_command = [sys.executable, "-c", "import time; time.sleep(5)"]
    path.write_text(
        f"""
[[agents]]
id = "shell"
label = "Shell"
command = {json.dumps(shell_command)}
cwd_mode = "optional"
stop_policy = "process_group"

[[agents]]
id = "sleeper"
label = "Sleeper"
command = {json.dumps(sleeper_command)}
cwd_mode = "optional"
stop_policy = "process_group"
""",
        encoding="utf-8",
    )


@contextmanager
def live_daemon(tmp_path: Path, port: int) -> Iterator[str]:
    registry_path = tmp_path / "agents.toml"
    write_smoke_registry(registry_path)
    app = create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry_path)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    wait_for_health(base_url)
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def wait_for_health(base_url: str) -> None:
    deadline = time.monotonic() + 5
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=0.2)
            if response.status_code == 200:
                return
        except httpx.RequestError as exc:
            last_error = exc
        time.sleep(0.05)
    raise AssertionError(f"daemon did not start: {last_error}")


def assert_cli_ok(result: Result) -> None:
    assert result.exit_code == 0, result.output


def session_id_from(output: str) -> str:
    return output.strip().split("\t")[0]


def json_from(output: str) -> dict[str, object]:
    data = json.loads(output)
    assert isinstance(data, dict)
    return data


def test_agentctl_shell_run_logs_retry_quickstart_against_live_daemon(
    tmp_path: Path,
    free_tcp_port: int,
) -> None:
    runner = CliRunner()
    with live_daemon(tmp_path, free_tcp_port) as api:
        agents = runner.invoke(cli.app, ["agents", "list", "--api", api])
        assert_cli_ok(agents)
        assert "shell\tShell\tenabled" in agents.output

        run = runner.invoke(
            cli.app,
            ["run", "shell", "--cwd", str(tmp_path), "--message", "OK", "--api", api],
        )
        assert_cli_ok(run)
        original_id = session_id_from(run.output)
        assert run.output == f"{original_id}\tshell\tsucceeded\n"

        logs = runner.invoke(cli.app, ["logs", original_id, "--api", api])
        assert_cli_ok(logs)
        assert logs.output == "stdout\tOK\n"

        retry = runner.invoke(cli.app, ["retry", original_id, "--api", api])
        assert_cli_ok(retry)
        retry_id = session_id_from(retry.output)
        assert retry_id != original_id
        assert retry.output == f"{retry_id}\tshell\tsucceeded\n"

        sessions = runner.invoke(cli.app, ["sessions", "list", "--api", api])
        assert_cli_ok(sessions)
        assert original_id in sessions.output
        assert retry_id in sessions.output

        for session_id in (original_id, retry_id):
            session = httpx.get(f"{api}/sessions/{session_id}", timeout=1).json()
            assert Path(session["artifact_dir"]).is_dir()
            assert Path(session["stdout_log"]).is_file()
            assert Path(session["stderr_log"]).is_file()


def test_agentctl_stop_running_session_against_live_daemon(
    tmp_path: Path,
    free_tcp_port: int,
) -> None:
    runner = CliRunner()
    with live_daemon(tmp_path, free_tcp_port) as api:
        run = runner.invoke(
            cli.app,
            ["run", "sleeper", "--cwd", str(tmp_path), "--message", "ignored", "--api", api],
        )
        assert_cli_ok(run)
        session_id = session_id_from(run.output)
        assert run.output == f"{session_id}\tsleeper\trunning\n"

        stop = runner.invoke(cli.app, ["stop", session_id, "--api", api])
        assert_cli_ok(stop)
        assert stop.output == f"{session_id}\tstopped\n"

        session = httpx.get(f"{api}/sessions/{session_id}", timeout=1).json()
        assert session["status"] == "stopped"


def test_agentctl_memory_pipeline_against_live_daemon(
    tmp_path: Path,
    free_tcp_port: int,
) -> None:
    runner = CliRunner()
    memory_text = "approved memory fact"
    with live_daemon(tmp_path, free_tcp_port) as api:
        run = runner.invoke(
            cli.app,
            ["run", "shell", "--cwd", str(tmp_path), "--message", memory_text, "--api", api],
        )
        assert_cli_ok(run)
        session_id = session_id_from(run.output)
        assert run.output == f"{session_id}\tshell\tsucceeded\n"

        summarize = runner.invoke(cli.app, ["memory", "summarize", session_id, "--api", api])
        assert_cli_ok(summarize)
        summary = json_from(summarize.output)
        assert summary["session_id"] == session_id
        assert summary["agent_id"] == "shell"
        assert summary["one_liner"] == memory_text

        review = runner.invoke(
            cli.app,
            ["memory", "review", "create", session_id, "--api", api],
        )
        assert_cli_ok(review)
        review_item = json_from(review.output)
        assert review_item["session_id"] == session_id
        assert review_item["status"] == "pending"

        approve = runner.invoke(
            cli.app,
            ["memory", "approve", str(review_item["id"]), "--api", api],
        )
        assert_cli_ok(approve)
        memory = json_from(approve.output)
        assert memory["session_id"] == session_id
        assert memory["review_item_id"] == review_item["id"]
        assert memory["title"] == memory_text

        search = runner.invoke(cli.app, ["memory", "search", "approved", "--api", api])
        assert_cli_ok(search)
        assert session_id in search.output
        assert memory_text in search.output
