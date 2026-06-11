from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import httpx
import typer

from agentic_os.bench import run_slo_benchmark
from agentic_os.client import AgenticClient


DEFAULT_API = "http://127.0.0.1:8767"

app = typer.Typer(help="Control local agentic-os sessions.")
agents = typer.Typer(help="Inspect configured agents.")
sessions = typer.Typer(help="Inspect local sessions.")
approvals = typer.Typer(help="Inspect and decide pending approvals.")
memory = typer.Typer(help="Inspect and promote session memory.")
memory_review = typer.Typer(help="Inspect and manage memory review items.")
skills = typer.Typer(help="Inspect and manage local skill registry records.")
mcp = typer.Typer(help="Inspect and manage local MCP registry records.")
policy = typer.Typer(help="Inspect and evaluate local capability policy.")
bench = typer.Typer(help="Run local benchmark checks.")
app.add_typer(agents, name="agents")
harnesses_cmd = typer.Typer(help="Inspect harness instances and activity.")
app.add_typer(harnesses_cmd, name="harnesses")
app.add_typer(sessions, name="sessions")
app.add_typer(approvals, name="approvals")
app.add_typer(memory, name="memory")
app.add_typer(skills, name="skills")
app.add_typer(mcp, name="mcp")
app.add_typer(policy, name="policy")
app.add_typer(bench, name="bench")
memory.add_typer(memory_review, name="review")
fleet = typer.Typer(help="Inspect fleet health, events, and capacity.")
app.add_typer(fleet, name="fleet")
audit = typer.Typer(help="Query governance audit trail.")
app.add_typer(audit, name="audit")
catalog = typer.Typer(help="Scan and inspect workflow surfaces.")
app.add_typer(catalog, name="catalog")
patches_cmd = typer.Typer(help="Inspect and rollback config patches.")
app.add_typer(patches_cmd, name="patches")
config_cmd = typer.Typer(help="Inspect configuration scopes.")
app.add_typer(config_cmd, name="config")
harness_config_cmd = typer.Typer(help="Inspect and patch harness-native configuration.")
app.add_typer(harness_config_cmd, name="harness-config")
harness_contract_cmd = typer.Typer(help="Inspect harness adapter contracts.")
app.add_typer(harness_contract_cmd, name="harness-contracts")
profiles_cmd = typer.Typer(help="Inspect and bind run profiles.")
app.add_typer(profiles_cmd, name="profiles")
usage_cmd = typer.Typer(help="Inspect token/cost usage.")
app.add_typer(usage_cmd, name="usage")

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
            if "approval_id" in payload:
                parts.append(f"approval_id={payload['approval_id']}")
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


@harnesses_cmd.command("validate")
def harnesses_validate(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).harnesses_validate())
    if data.get("warnings"):
        for warning in data["warnings"]:
            typer.echo(f"warning: {warning}", err=True)
    if not data.get("ok"):
        for error in data.get("errors", []):
            typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1)
    typer.echo("registry validation ok")


@harness_contract_cmd.command("list")
def harness_contracts_list(
    version: str = typer.Option("v1", "--version", help="Harness contract version."),
    api: str | None = _api_option(),
) -> None:
    client = make_client(api)
    data = _run_api_call(
        client.list_harness_contracts
        if version == "v1"
        else lambda: client.list_harness_contracts(version=version)
    )
    if version == "v2":
        _echo_json(data)
        return
    for contract in data.get("contracts", []):
        typer.echo(
            f"{contract['harness_id']}\t{contract['contract_version']}\t{contract['required_env']}"
        )


@harness_contract_cmd.command("show")
def harness_contracts_show(
    harness_id: str,
    version: str = typer.Option("v1", "--version", help="Harness contract version."),
    api: str | None = _api_option(),
) -> None:
    client = make_client(api)
    _echo_json(
        _run_api_call(
            lambda: (
                client.show_harness_contract(harness_id)
                if version == "v1"
                else client.show_harness_contract(harness_id, version=version)
            )
        )
    )


@profiles_cmd.command("list")
def profiles_list(
    cwd: Path | None = typer.Option(None, "--cwd", help="Working directory for profile lookup."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd is not None else None
    _echo_json(_run_api_call(lambda: make_client(api).list_profiles(resolved_cwd)))


@profiles_cmd.command("show")
def profiles_show(name: str, api: str | None = _api_option()) -> None:
    _echo_json(_run_api_call(lambda: make_client(api).show_profile(name)))


@profiles_cmd.command("set")
def profiles_set(
    name: str,
    harness: str = typer.Option(..., "--harness"),
    provider: str = typer.Option(..., "--provider"),
    model: str = typer.Option(..., "--model"),
    message_prefix: str = typer.Option("", "--message-prefix"),
    max_tokens_budget: int | None = typer.Option(None, "--max-tokens-budget"),
    notes: str = typer.Option("", "--notes"),
    global_scope: bool = typer.Option(
        False, "--global", help="Write to ~/.agentic-os/profiles.toml"
    ),
    cwd: Path | None = typer.Option(None, "--cwd", help="Repo path for local profile file."),
    api: str | None = _api_option(),
) -> None:
    from agentic_os.profiles import RunProfileInput

    profile = RunProfileInput(
        name=name,
        harness_id=harness,
        provider=provider,
        model=model,
        message_prefix=message_prefix,
        max_tokens_budget=max_tokens_budget,
        notes=notes,
    )
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd is not None else None
    scope = "global" if global_scope else "local"
    _echo_json(
        _run_api_call(
            lambda: make_client(api).upsert_profile(
                profile.model_dump(),
                scope=scope,
                cwd=resolved_cwd,
            )
        )
    )


@profiles_cmd.command("bind")
def profiles_bind(
    project_path: Path,
    run_profile: str = typer.Option(..., "--run-profile"),
    api: str | None = _api_option(),
) -> None:
    resolved = str(project_path.expanduser().resolve())
    _echo_json(
        _run_api_call(
            lambda: make_client(api).bind_project_profile(resolved, run_profile),
        )
    )


@usage_cmd.command("summary")
def usage_summary_cmd(
    harness_id: str | None = typer.Option(None, "--harness-id"),
    provider: str | None = typer.Option(None, "--provider"),
    from_: str | None = typer.Option(None, "--from"),
    to: str | None = typer.Option(None, "--to"),
    api: str | None = _api_option(),
) -> None:
    _echo_json(
        _run_api_call(
            lambda: make_client(api).usage_summary(
                from_=from_,
                to=to,
                harness_id=harness_id,
                provider=provider,
            )
        )
    )


@usage_cmd.command("session")
def usage_session_cmd(session_id: str, api: str | None = _api_option()) -> None:
    _echo_json(_run_api_call(lambda: make_client(api).usage_session(session_id)))


@usage_cmd.command("quotas")
def usage_quotas_cmd(
    scope: str = typer.Option("daily", "--scope", help="daily or session"),
    api: str | None = _api_option(),
) -> None:
    _echo_json(_run_api_call(lambda: make_client(api).usage_quotas(scope=scope)))


@harnesses_cmd.command("activity")
def harness_activity_cmd(
    harness_id: str,
    event_type: str | None = typer.Option(None, "--type", help="Filter by event type."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).harness_activity(harness_id, event_type=event_type)
    )
    for entry in data.get("activity", []):
        typer.echo(f"{entry['timestamp']}\t{entry['type']}\t{entry['source']}\t{entry['message']}")


@app.command()
def run(
    agent_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Working directory."),
    message: str = typer.Option(..., "--message", help="Message passed to the agent."),
    profile: str | None = typer.Option(None, "--profile", help="Run profile name."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd is not None else None
    data = _run_api_call(
        lambda: make_client(api).run_session(
            agent_id=agent_id,
            cwd=resolved_cwd,
            message=message,
            profile=profile,
        )
    )
    typer.echo(f"{data['id']}\t{data['agent_id']}\t{data['status']}")


@sessions.command("list")
def sessions_list(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).list_sessions())
    for session in data["sessions"]:
        typer.echo(f"{session['id']}\t{session['agent_id']}\t{session['status']}")


@sessions.command("live")
def sessions_live(
    within_hours: int = typer.Option(72, "--within-hours", help="Scan window in hours."),
    limit: int = typer.Option(50, "--limit", help="Maximum sessions returned."),
    api: str | None = _api_option(),
) -> None:
    """List real external tool sessions discovered on this machine (P39)."""
    data = _run_api_call(
        lambda: make_client(api).list_live_sessions(within_hours=within_hours, limit=limit)
    )
    for session in data.get("sessions", []):
        marker = "ACTIVE" if session.get("active") else "idle"
        typer.echo(
            f"{marker}\t{session['tool']}\t{session['workspace']}\t"
            f"{session.get('title', '')}\t{session['last_activity_at']}\t{session['session_id']}"
        )


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


@sessions.command("evidence")
def sessions_evidence(session_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).get_session_evidence(session_id))
    _echo_json(data)


@sessions.command("evidence-events")
def sessions_evidence_events(
    session_id: str,
    after: int = typer.Option(0, "--after", help="Skip events through this line index."),
    max_lines: int = typer.Option(5000, "--max-lines", help="Maximum events to read."),
    json_output: bool = typer.Option(False, "--json", help="Print API envelope JSON."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).get_session_evidence_events(
            session_id,
            after=after,
            max_lines=max_lines,
        )
    )
    if json_output:
        _echo_json(data)
        return
    for event in data.get("events", []):
        typer.echo(json.dumps(event, ensure_ascii=False, sort_keys=True))


@sessions.command("timeline")
def sessions_timeline(
    session_id: str,
    event_type: str | None = typer.Option(None, "--type", help="Filter by event type."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).get_session_timeline(session_id, event_type=event_type)
    )
    for entry in data.get("timeline", []):
        typer.echo(f"{entry['timestamp']}\t{entry['type']}\t{entry['source']}\t{entry['message']}")


@sessions.command("attach")
def sessions_attach(
    session_id: str,
    mode: str = typer.Option("preview", "--mode", help="preview or exec."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(lambda: make_client(api).attach_session(session_id, mode=mode))
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
        if data.get("truncated"):
            typer.echo(f"(truncated at {len(entries)} lines)", err=True)
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


@approvals.command("list")
def approvals_list(
    status: str | None = typer.Option(
        None, "--status", help="Filter by status (pending/approved/rejected/expired)."
    ),
    harness_id: str | None = typer.Option(None, "--harness", help="Filter by harness id."),
    limit: int = typer.Option(500, "--limit", help="Max approvals to return."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).list_approvals(status=status, harness_id=harness_id, limit=limit)
    )
    for approval in data["approvals"]:
        typer.echo(
            f"{approval['id']}\t{approval['agent_id']}\t{approval['status']}\t"
            f"{approval['source_session_id']}\t"
            f"{approval.get('approved_session_id') or '-'}\t{approval.get('reason', '')}"
        )


@approvals.command("show")
def approvals_show(approval_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).show_approval(approval_id))
    _echo_json(data)


@approvals.command("approve")
def approvals_approve(approval_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).approve_approval(approval_id))
    _echo_json(data)


@approvals.command("reject")
def approvals_reject(
    approval_id: str,
    reason: str = typer.Option("", "--reason", help="Operator rejection reason."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(lambda: make_client(api).reject_approval(approval_id, reason))
    _echo_json(data)


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
        if skill.get("deprecated"):
            enabled = "deprecated"
        elif skill.get("enabled", True):
            enabled = "enabled"
        else:
            enabled = "disabled"
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


@skills.command("deprecate")
def skills_deprecate(
    skill_id: str,
    reason: str = typer.Option("", "--reason", help="Deprecation reason."),
    replacement: str | None = typer.Option(None, "--replacement", help="Replacement record id."),
    sunset: str | None = typer.Option(None, "--sunset", help="Sunset timestamp."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).deprecate_skill(
            skill_id,
            reason=reason,
            replacement_id=replacement,
            sunset_at=sunset,
        )
    )
    _echo_json(data)


@skills.command("undeprecate")
def skills_undeprecate(skill_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).undeprecate_skill(skill_id))
    _echo_json(data)


@mcp.command("list")
def mcp_list(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).list_mcp_servers())
    for server in data["servers"]:
        if server.get("deprecated"):
            enabled = "deprecated"
        elif server.get("enabled", True):
            enabled = "enabled"
        else:
            enabled = "disabled"
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


@mcp.command("deprecate")
def mcp_deprecate(
    server_id: str,
    reason: str = typer.Option("", "--reason", help="Deprecation reason."),
    replacement: str | None = typer.Option(None, "--replacement", help="Replacement record id."),
    sunset: str | None = typer.Option(None, "--sunset", help="Sunset timestamp."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).deprecate_mcp_server(
            server_id,
            reason=reason,
            replacement_id=replacement,
            sunset_at=sunset,
        )
    )
    _echo_json(data)


@mcp.command("undeprecate")
def mcp_undeprecate(server_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).undeprecate_mcp_server(server_id))
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
        if item.get("deprecated"):
            enabled = "deprecated"
        elif item.get("enabled", True):
            enabled = "enabled"
        else:
            enabled = "disabled"
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


@policy.command("deprecate")
def policy_deprecate(
    agent_id: str,
    reason: str = typer.Option("", "--reason", help="Deprecation reason."),
    replacement: str | None = typer.Option(None, "--replacement", help="Replacement record id."),
    sunset: str | None = typer.Option(None, "--sunset", help="Sunset timestamp."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).deprecate_policy(
            agent_id,
            reason=reason,
            replacement_id=replacement,
            sunset_at=sunset,
        )
    )
    _echo_json(data)


@policy.command("undeprecate")
def policy_undeprecate(agent_id: str, api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).undeprecate_policy(agent_id))
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


@bench.command("slo")
def bench_slo(
    iterations: int = typer.Option(100, "--iterations", min=1, help="Iterations per operation."),
    output: Path | None = typer.Option(None, "--output", help="Write full JSON report."),
    api: str | None = typer.Option(None, "--api", help="Explicit test daemon API URL."),
) -> None:
    if api is None:
        typer.echo("bench slo requires --api pointing at an explicit test daemon", err=True)
        raise typer.Exit(1)
    report = _run_api_call(lambda: run_slo_benchmark(make_client(api), iterations))
    report["api"] = api
    typer.echo(f"passed: {'yes' if report['passed'] else 'no'}")
    for result in report["results"]:
        typer.echo(
            f"{result['name']}\tp99={result['p99_ms']}ms\t"
            f"target={result['target_ms_p99']}ms\tpassed={result['passed']}"
        )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["passed"]:
        raise typer.Exit(2)


@audit.command("events")
def audit_events_cmd(
    domain: str | None = typer.Option(None, "--domain", help="Filter by domain."),
    entity_id: str | None = typer.Option(None, "--entity", help="Filter by entity id."),
    event_type: str | None = typer.Option(None, "--type", help="Filter by event type."),
    limit: int = typer.Option(500, "--limit", help="Max events to return."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(
        lambda: make_client(api).audit_events(
            domain=domain, entity_id=entity_id, event_type=event_type, limit=limit
        )
    )
    for event in data.get("events", []):
        typer.echo(
            f"{event.get('id', '-')}\t{event['domain']}\t{event['entity_id']}\t"
            f"{event['event_type']}\t{event['message']}\t{event['created_at']}"
        )


@audit.command("coverage")
def audit_coverage_cmd(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).audit_policy_coverage())
    for item in data.get("coverage", []):
        has_policy = "yes" if item["has_policy"] else "no"
        last_eval = item.get("last_evaluated_at") or "-"
        uncovered = len(item.get("runs_without_policy_evaluation", []))
        typer.echo(
            f"{item['agent_id']}\tpolicy={has_policy}\tlast_eval={last_eval}\t"
            f"runs={item['recent_run_count']}\tuncovered={uncovered}"
        )


@catalog.command("list")
def catalog_list(
    harness: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    scope: str | None = typer.Option(None, "--scope", help="Filter by scope (user/project/local)."),
    surface_type: str | None = typer.Option(None, "--type", help="Filter by surface type."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else None
    data = _run_api_call(
        lambda: make_client(api).catalog_surfaces(
            harness, cwd=resolved_cwd, scope=scope, surface_type=surface_type
        )
    )
    for surface in data.get("surfaces", []):
        typer.echo(
            f"{surface['id']}\t{surface['type']}\t{surface['scope']}\t"
            f"{surface['source']}\t{'enabled' if surface['enabled'] else 'disabled'}"
        )


@catalog.command("merged")
def catalog_merged(
    harness: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else None
    data = _run_api_call(lambda: make_client(api).catalog_merged(harness, cwd=resolved_cwd))
    for surface in data.get("surfaces", []):
        override_info = ""
        if surface.get("overridden_by"):
            override_info = f" [overridden by {surface['overridden_by']}]"
        elif surface.get("overrides"):
            override_info = f" [overrides {surface['overrides']}]"
        typer.echo(f"{surface['id']}\t{surface['scope']}{override_info}")


@catalog.command("diff")
def catalog_diff_cmd(
    harness: str,
    cwd_a: Path | None = typer.Option(None, "--cwd-a", help="First project directory."),
    cwd_b: Path | None = typer.Option(None, "--cwd-b", help="Second project directory."),
    scope_a: str | None = typer.Option(None, "--scope-a", help="First scope filter."),
    scope_b: str | None = typer.Option(None, "--scope-b", help="Second scope filter."),
    api: str | None = _api_option(),
) -> None:
    resolved_a = str(cwd_a.expanduser().resolve()) if cwd_a else None
    resolved_b = str(cwd_b.expanduser().resolve()) if cwd_b else None
    data = _run_api_call(
        lambda: make_client(api).catalog_diff(
            harness,
            cwd_a=resolved_a,
            cwd_b=resolved_b,
            scope_a=scope_a,
            scope_b=scope_b,
        )
    )
    for s in data.get("added", []):
        typer.echo(f"+ {s['id']}\t{scope_b or ''}")
    for s in data.get("removed", []):
        typer.echo(f"- {s['id']}\t{scope_a or ''}")
    for m in data.get("modified", []):
        typer.echo(f"~ {m['surface']['id']}")


@catalog.command("patch")
def catalog_patch_cmd(
    harness: str,
    op: list[str] = typer.Option(..., "--op", help="JSON semantic op (repeatable)."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without writing."),
    api: str | None = _api_option(),
) -> None:
    ops = [json.loads(item) for item in op]
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else str(Path.cwd())
    _echo_json(
        _run_api_call(
            lambda: make_client(api).catalog_patch(
                harness,
                ops,
                cwd=resolved_cwd,
                dry_run=dry_run,
            )
        )
    )


@patches_cmd.command("list")
def patches_list_cmd(
    harness: str | None = typer.Option(None, "--harness", help="Filter by harness id."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Filter by project directory."),
    limit: int = typer.Option(50, "--limit", help="Maximum entries to return."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else None
    _echo_json(
        _run_api_call(
            lambda: make_client(api).patches_list(
                harness=harness,
                cwd=resolved_cwd,
                limit=limit,
            )
        )
    )


@patches_cmd.command("show")
def patches_show_cmd(
    patch_id: str,
    api: str | None = _api_option(),
) -> None:
    _echo_json(_run_api_call(lambda: make_client(api).patches_show(patch_id)))


@patches_cmd.command("rollback")
def patches_rollback_cmd(
    patch_id: str,
    api: str | None = _api_option(),
) -> None:
    _echo_json(_run_api_call(lambda: make_client(api).patches_rollback(patch_id)))


@config_cmd.command("effective")
def config_effective(
    harness_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else None
    data = _run_api_call(lambda: make_client(api).config_effective(harness_id, cwd=resolved_cwd))
    typer.echo(f"harness: {data['harness_id']}")
    typer.echo(f"scopes: {', '.join(data.get('scopes_present', []))}")
    typer.echo("")
    for entry in data.get("entries", []):
        typer.echo(f"{entry['key']}\t{entry['value']}\t[{entry['scope']}]\t{entry['source']}")


@config_cmd.command("diff")
def config_diff_cmd(
    harness_id: str,
    scope_a: str = typer.Option("user", "--scope-a", help="First scope."),
    scope_b: str = typer.Option("project", "--scope-b", help="Second scope."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else None
    data = _run_api_call(
        lambda: make_client(api).config_diff(
            harness_id, scope_a=scope_a, scope_b=scope_b, cwd=resolved_cwd
        )
    )
    for item in data.get("added", []):
        typer.echo(f"+ {item['key']}\t{item['value']}\t[{item['scope']}]")
    for item in data.get("removed", []):
        typer.echo(f"- {item['key']}\t{item['value']}\t[{item['scope']}]")
    for item in data.get("modified", []):
        typer.echo(f"~ {item['key']}\t{item['before']['value']} -> {item['after']['value']}")


@config_cmd.command("explain")
def config_explain(
    harness_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else None
    data = _run_api_call(lambda: make_client(api).config_explain(harness_id, cwd=resolved_cwd))
    for entry in data.get("entries", []):
        typer.echo(f"{entry['key']}\t[{entry['scope']}]\t{entry['source']}")


@config_cmd.command("patch")
def config_patch_cmd(
    harness_id: str,
    scope: str = typer.Option(..., "--scope", help="Config scope: user, project, or local."),
    op: list[str] | None = typer.Option(None, "--op", help="JSON patch op (repeatable)."),
    file: Path | None = typer.Option(None, "--file", help="JSON file with ops array or {ops: [...]}."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without writing."),
    api: str | None = _api_option(),
) -> None:
    if file is None and not op:
        raise typer.BadParameter("provide --file or at least one --op")
    if file is not None:
        payload = json.loads(file.read_text(encoding="utf-8"))
        ops = payload["ops"] if isinstance(payload, dict) and "ops" in payload else payload
    else:
        ops = [json.loads(item) for item in op or []]
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else str(Path.cwd())
    _echo_json(
        _run_api_call(
            lambda: make_client(api).config_patch(
                harness_id,
                ops,
                scope=scope,
                cwd=resolved_cwd,
                dry_run=dry_run,
            )
        )
    )


@harness_config_cmd.command("effective")
def harness_config_effective_cmd(
    harness_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else None
    data = _run_api_call(
        lambda: make_client(api).harness_config_effective(harness_id, cwd=resolved_cwd)
    )
    typer.echo(f"harness: {data['harness_id']}")
    typer.echo(f"scopes: {', '.join(data.get('scopes_present', []))}")
    typer.echo("")
    for entry in data.get("entries", []):
        typer.echo(f"{entry['key']}\t{entry['value']}\t[{entry['scope']}]\t{entry['source']}")


@harness_config_cmd.command("diff")
def harness_config_diff_cmd(
    harness_id: str,
    scope_a: str = typer.Option("user", "--scope-a", help="First scope."),
    scope_b: str = typer.Option("project", "--scope-b", help="Second scope."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else None
    data = _run_api_call(
        lambda: make_client(api).harness_config_diff(
            harness_id, scope_a=scope_a, scope_b=scope_b, cwd=resolved_cwd
        )
    )
    for item in data.get("added", []):
        typer.echo(f"+ {item['key']}\t{item['value']}\t[{item['scope']}]")
    for item in data.get("removed", []):
        typer.echo(f"- {item['key']}\t{item['value']}\t[{item['scope']}]")
    for item in data.get("modified", []):
        typer.echo(f"~ {item['key']}\t{item['before']['value']} -> {item['after']['value']}")


@harness_config_cmd.command("explain")
def harness_config_explain_cmd(
    harness_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    api: str | None = _api_option(),
) -> None:
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else None
    data = _run_api_call(
        lambda: make_client(api).harness_config_explain(harness_id, cwd=resolved_cwd)
    )
    for entry in data.get("entries", []):
        typer.echo(f"{entry['key']}\t[{entry['scope']}]\t{entry['source']}")


@harness_config_cmd.command("patch")
def harness_config_patch_cmd(
    harness_id: str,
    scope: str = typer.Option(..., "--scope", help="Config scope: user, project, or local."),
    op: list[str] | None = typer.Option(None, "--op", help="JSON patch op (repeatable)."),
    file: Path | None = typer.Option(None, "--file", help="JSON file with ops array or {ops: [...]}."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without writing."),
    api: str | None = _api_option(),
) -> None:
    if file is None and not op:
        raise typer.BadParameter("provide --file or at least one --op")
    if file is not None:
        payload = json.loads(file.read_text(encoding="utf-8"))
        ops = payload["ops"] if isinstance(payload, dict) and "ops" in payload else payload
    else:
        ops = [json.loads(item) for item in op or []]
    resolved_cwd = str(cwd.expanduser().resolve()) if cwd else str(Path.cwd())
    _echo_json(
        _run_api_call(
            lambda: make_client(api).harness_config_patch(
                harness_id,
                ops,
                scope=scope,
                cwd=resolved_cwd,
                dry_run=dry_run,
            )
        )
    )
