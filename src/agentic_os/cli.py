from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import httpx
import typer

from agentic_os.client import AgenticClient


DEFAULT_API = "http://127.0.0.1:8767"

app = typer.Typer(help="Control local agentic-os sessions.")
agents = typer.Typer(help="Inspect configured agents.")
sessions = typer.Typer(help="Inspect local sessions.")
app.add_typer(agents, name="agents")
app.add_typer(sessions, name="sessions")

T = TypeVar("T")


def make_client(api: str | None) -> AgenticClient:
    return AgenticClient(api or os.environ.get("AGENTIC_OS_API", DEFAULT_API))


def _run_api_call(call: Callable[[], T]) -> T:
    try:
        return call()
    except httpx.HTTPStatusError as exc:
        detail = _http_error_detail(exc.response)
        typer.echo(f"HTTP {exc.response.status_code}: {detail}", err=True)
        raise typer.Exit(1) from None
    except httpx.RequestError as exc:
        typer.echo(f"Request failed: {exc}", err=True)
        raise typer.Exit(1) from None


def _http_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload["detail"]
    else:
        detail = payload
    if isinstance(detail, str):
        return detail
    return json.dumps(detail, ensure_ascii=False)


def _echo_json(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _api_option() -> typer.Option:
    return typer.Option(None, "--api", help="Daemon API URL.")


@agents.command("list")
def agents_list(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).list_agents())
    for agent in data["agents"]:
        enabled = "enabled" if agent.get("enabled", True) else "disabled"
        typer.echo(f"{agent['id']}\t{agent.get('label', '')}\t{enabled}")


@agents.command("show")
def agents_show(agent_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).show_agent(agent_id))
    _echo_json(data)


@app.command()
def run(
    agent_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Working directory."),
    message: str = typer.Option(..., "--message", help="Message passed to the agent."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd is not None else None
    data = _run_api_call(
        lambda: make_client(api).run_session(agent_id=agent_id, cwd=resolved_cwd, message=message)
    )
    typer.echo(f"{data['id']}\t{data['agent_id']}\t{data['status']}")


@sessions.command("list")
def sessions_list(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).list_sessions())
    for session in data["sessions"]:
        typer.echo(f"{session['id']}\t{session['agent_id']}\t{session['status']}")


@sessions.command("show")
def sessions_show(session_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).show_session(session_id))
    _echo_json(data)


@app.command()
def logs(
    session_id: str,
    stream: str | None = typer.Option(None, "--stream", help="stdout or stderr."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Poll for new log lines."),
    api: str | None = _api_option(),
) -> None:
    client = make_client(api)
    after = 0
    while True:
        data = _run_api_call(lambda: client.get_logs(session_id, stream=stream, after=after))
        entries = data["entries"]
        for entry in entries:
            typer.echo(f"{entry['stream']}\t{entry['line']}")
            after = max(after, entry["index"])
        if not follow:
            return
        time.sleep(1)


@app.command()
def stop(session_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).stop_session(session_id))
    typer.echo(f"{data['id']}\t{data['status']}")


@app.command()
def retry(session_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).retry_session(session_id))
    typer.echo(f"{data['id']}\t{data['agent_id']}\t{data['status']}")
