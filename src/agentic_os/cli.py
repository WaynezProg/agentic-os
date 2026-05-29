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
memory = typer.Typer(help="Inspect and promote session memory.")
memory_review = typer.Typer(help="Inspect and manage memory review items.")
skills = typer.Typer(help="Inspect and manage local skill registry records.")
mcp = typer.Typer(help="Inspect and manage local MCP registry records.")
policy = typer.Typer(help="Inspect and evaluate local capability policy.")
app.add_typer(agents, name="agents")
app.add_typer(sessions, name="sessions")
app.add_typer(memory, name="memory")
app.add_typer(skills, name="skills")
app.add_typer(mcp, name="mcp")
app.add_typer(policy, name="policy")
memory.add_typer(memory_review, name="review")
fleet = typer.Typer(help="Inspect fleet health, events, and capacity.")
app.add_typer(fleet, name="fleet")

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
    except ValueError as exc:
        typer.echo(f"Invalid request: {exc}", err=True)
        raise typer.Exit(1) from None


def _http_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict):
        if "decision" in payload:
            parts = [f"decision={payload['decision']}"]
            if "detail" in payload:
                parts.append(str(payload["detail"]))
            if "session_id" in payload:
                parts.append(f"session_id={payload['session_id']}")
            return "  ".join(parts)
        if "detail" in payload:
            detail = payload["detail"]
            if isinstance(detail, str):
                return detail
            return json.dumps(detail, ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)


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


@sessions.command("events")
def sessions_events(session_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).get_session_events(session_id))
    for event in data.get("events", []):
        typer.echo(
            f"{event.get('id', '-')}\t{event['event_type']}\t"
            f"{event['message']}\t{event['created_at']}"
        )


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


@memory.command("summarize")
def memory_summarize(session_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).summarize_session(session_id))
    _echo_json(data)


@memory_review.command("create")
def memory_review_create(session_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).create_memory_review(session_id))
    _echo_json(data)


@memory_review.command("list")
def memory_review_list(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).list_memory_review())
    for item in data["items"]:
        typer.echo(f"{item['id']}\t{item['session_id']}\t{item['status']}\t{item.get('title', '')}")


@memory.command("approve")
def memory_approve(item_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).approve_memory_review(item_id))
    _echo_json(data)


@memory.command("reject")
def memory_reject(item_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).reject_memory_review(item_id))
    _echo_json(data)


@memory.command("list")
def memory_list(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).list_memories())
    for item in data["memories"]:
        typer.echo(
            f"{item['id']}\t{item['session_id']}\t{item.get('kind', '')}\t{item.get('title', '')}"
        )


@memory.command("search")
def memory_search(query: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).search_memories(query))
    for item in data["memories"]:
        typer.echo(
            f"{item['id']}\t{item['session_id']}\t{item.get('kind', '')}\t{item.get('title', '')}"
        )


@skills.command("list")
def skills_list(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).list_skills())
    for skill in data["skills"]:
        enabled = "enabled" if skill.get("enabled", True) else "disabled"
        tags = ",".join(skill.get("tags") or [])
        typer.echo(
            f"{skill['id']}\t{skill.get('label', '')}\t{enabled}\t{skill.get('source', '')}\t{tags}"
        )


@skills.command("show")
def skills_show(skill_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).show_skill(skill_id))
    _echo_json(data)


@skills.command("upsert")
def skills_upsert(
    skill_id: str,
    label: str = typer.Option(..., "--label", help="Skill label."),
    description: str = typer.Option("", "--description", help="Skill description."),
    source: str = typer.Option("local", "--source", help="Skill source."),
    entrypoint: str = typer.Option("", "--entrypoint", help="Non-executed entrypoint hint."),
    tags: list[str] | None = typer.Option(None, "--tag", help="Skill tag."),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Initial enabled state."),
    api: str | None = _api_option(),
) -> None:
    payload: dict[str, object] = {
        "label": label,
        "description": description,
        "source": source,
        "entrypoint": entrypoint,
        "tags": tags or [],
        "enabled": enabled,
    }
    data = _run_api_call(lambda: make_client(api).upsert_skill(skill_id, payload))
    _echo_json(data)


@skills.command("disable")
def skills_disable(skill_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).disable_skill(skill_id))
    _echo_json(data)


@mcp.command("list")
def mcp_list(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).list_mcp_servers())
    for server in data["servers"]:
        enabled = "enabled" if server.get("enabled", True) else "disabled"
        command_preview = " ".join(server.get("command_preview") or [])
        typer.echo(
            f"{server['id']}\t{server.get('label', '')}\t{enabled}\t"
            f"{server.get('transport', '')}\t{command_preview}"
        )


@mcp.command("show")
def mcp_show(server_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).show_mcp_server(server_id))
    _echo_json(data)


@mcp.command("upsert")
def mcp_upsert(
    server_id: str,
    label: str = typer.Option(..., "--label", help="MCP server label."),
    description: str = typer.Option("", "--description", help="MCP server description."),
    transport: str = typer.Option("stdio", "--transport", help="stdio, http, or sse."),
    command_preview: list[str] | None = typer.Option(
        None,
        "--command-preview",
        help="Display-only command preview part.",
    ),
    url: str | None = typer.Option(None, "--url", help="Display-only MCP URL."),
    env_keys: list[str] | None = typer.Option(
        None,
        "--env-key",
        help="Environment variable name only; values are not accepted.",
    ),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Initial enabled state."),
    api: str | None = _api_option(),
) -> None:
    payload: dict[str, object] = {
        "label": label,
        "description": description,
        "transport": transport,
        "command_preview": command_preview or [],
        "url": url,
        "env_keys": env_keys or [],
        "enabled": enabled,
    }
    data = _run_api_call(lambda: make_client(api).upsert_mcp_server(server_id, payload))
    _echo_json(data)


@mcp.command("disable")
def mcp_disable(server_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).disable_mcp_server(server_id))
    _echo_json(data)


@policy.command("show")
def policy_show(
    agent_id: str | None = typer.Argument(None, help="Agent id."),
    api: str | None = _api_option(),
) -> None:
    client = make_client(api)
    if agent_id:
        data = _run_api_call(lambda: client.show_policy(agent_id))
        _echo_json(data)
        return

    data = _run_api_call(client.list_policies)
    for item in data["policies"]:
        enabled = "enabled" if item.get("enabled", True) else "disabled"
        mode = "readonly" if item.get("readonly", False) else "write"
        typer.echo(
            f"{item['agent_id']}\t{enabled}\t{mode}\t{item.get('rate_limit_per_minute', '')}"
        )


@policy.command("set")
def policy_set(
    agent_id: str,
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Policy enabled state."),
    readonly: bool = typer.Option(False, "--readonly", help="Deny write-capable tools."),
    skill_ids: list[str] | None = typer.Option(None, "--skill", help="Allowed skill id."),
    mcp_server_ids: list[str] | None = typer.Option(None, "--mcp", help="Allowed MCP server id."),
    tool_names: list[str] | None = typer.Option(None, "--tool", help="Allowed tool name."),
    approval_tools: list[str] | None = typer.Option(
        None,
        "--approval-tool",
        help="Tool name that requires approval.",
    ),
    model_ids: list[str] | None = typer.Option(None, "--model", help="Allowed model id."),
    cwd_roots: list[str] | None = typer.Option(None, "--cwd-root", help="Allowed cwd root."),
    rate_limit: int = typer.Option(60, "--rate-limit", help="Declarative rate limit."),
    api: str | None = _api_option(),
) -> None:
    payload: dict[str, object] = {
        "enabled": enabled,
        "readonly": readonly,
        "allowed_skill_ids": skill_ids or [],
        "allowed_mcp_server_ids": mcp_server_ids or [],
        "allowed_tool_names": tool_names or [],
        "approval_required_tool_names": approval_tools or [],
        "allowed_model_ids": model_ids or [],
        "cwd_roots": cwd_roots or [],
        "rate_limit_per_minute": rate_limit,
    }
    data = _run_api_call(lambda: make_client(api).upsert_policy(agent_id, payload))
    _echo_json(data)


@policy.command("evaluate")
def policy_evaluate(
    agent_id: str,
    skill_id: str | None = typer.Option(None, "--skill", help="Requested skill id."),
    mcp_server_id: str | None = typer.Option(None, "--mcp", help="Requested MCP server id."),
    tool_name: str | None = typer.Option(None, "--tool", help="Requested tool name."),
    model_id: str | None = typer.Option(None, "--model", help="Requested model id."),
    cwd: str | None = typer.Option(None, "--cwd", help="Requested working directory."),
    api: str | None = _api_option(),
) -> None:
    payload: dict[str, object] = {
        "agent_id": agent_id,
        "skill_id": skill_id,
        "mcp_server_id": mcp_server_id,
        "tool_name": tool_name,
        "model_id": model_id,
        "cwd": cwd,
    }
    data = _run_api_call(lambda: make_client(api).evaluate_policy(payload))
    _echo_json(data)


@fleet.command("health")
def fleet_health(
    agent_id: str | None = typer.Argument(None, help="Show health for a specific agent."),
    api: str | None = _api_option(),
) -> None:
    client = make_client(api)
    if agent_id:
        data = _run_api_call(lambda: client.fleet_instance_health(agent_id))
        _echo_json(data)
        return
    data = _run_api_call(client.fleet_health)
    for instance in data.get("instances", []):
        typer.echo(
            f"{instance['agent_id']}\t{instance['state']}\t"
            f"{instance.get('version', '-')}\t{instance['message']}"
        )


@fleet.command("events")
def fleet_events_cmd(
    agent_id: str | None = typer.Option(None, "--agent", help="Filter by agent."),
    event_type: str | None = typer.Option(None, "--type", help="Filter by event type."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).fleet_events(agent_id=agent_id, event_type=event_type)
    )
    for event in data.get("events", []):
        typer.echo(
            f"{event.get('id', '-')}\t{event['agent_id']}\t"
            f"{event['event_type']}\t{event['message']}\t{event['created_at']}"
        )


@fleet.command("capacity")
def fleet_capacity_cmd(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).fleet_capacity())
    typer.echo(f"sessions: {data['running_sessions']}/{data['max_running_sessions']}")
    typer.echo(f"instances: {data['registered_instances']}/{data['max_registered_instances']}")


@fleet.command("probe")
def fleet_probe_cmd(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).fleet_probe())
    typer.echo(f"Probed {data['probed']} instances")
