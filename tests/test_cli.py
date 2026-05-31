from __future__ import annotations

import json
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

    def run_session(
        self,
        agent_id: str,
        cwd: str | None,
        message: str,
        profile: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(("run_session", (agent_id, cwd, message), {"profile": profile}))
        return {"id": "s_1", "agent_id": agent_id, "cwd": cwd, "status": "succeeded"}

    def list_harness_contracts(self, version: str = "v1") -> dict[str, object]:
        self.calls.append(("list_harness_contracts", (), {"version": version}))
        return {
            "contracts": [
                {
                    "harness_id": "shell",
                    "contract_version": version,
                    "required_env": [],
                }
            ],
            "count": 1,
        }

    def show_harness_contract(self, harness_id: str, version: str = "v1") -> dict[str, object]:
        self.calls.append(("show_harness_contract", (harness_id,), {"version": version}))
        return {"harness_id": harness_id, "contract_version": version}

    def list_profiles(self, cwd: str | None = None) -> dict[str, object]:
        self.calls.append(("list_profiles", (), {"cwd": cwd}))
        return {"run_profiles": [], "project_bindings": []}

    def show_profile(self, name: str) -> dict[str, object]:
        self.calls.append(("show_profile", (name,), {}))
        return {"name": name, "harness_id": "shell"}

    def bind_project_profile(self, project_path: str, run_profile: str) -> dict[str, object]:
        self.calls.append(
            ("bind_project_profile", (project_path, run_profile), {}),
        )
        return {"project_path": project_path, "run_profile": run_profile}

    def usage_summary(
        self,
        *,
        from_: str | None = None,
        to: str | None = None,
        harness_id: str | None = None,
        provider: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "usage_summary",
                (),
                {
                    "from_": from_,
                    "to": to,
                    "harness_id": harness_id,
                    "provider": provider,
                },
            ),
        )
        return {"count": 0, "rows": []}

    def usage_session(self, session_id: str) -> dict[str, object]:
        self.calls.append(("usage_session", (session_id,), {}))
        return {"session_id": session_id, "total_tokens": 0}

    def usage_quotas(self, scope: str = "daily") -> dict[str, object]:
        self.calls.append(("usage_quotas", (), {"scope": scope}))
        return {"scope": scope, "rows": []}

    def list_sessions(self) -> dict[str, object]:
        self.calls.append(("list_sessions", (), {}))
        return {"sessions": [{"id": "s_1", "agent_id": "shell", "status": "succeeded"}]}

    def show_session(self, session_id: str) -> dict[str, object]:
        self.calls.append(("show_session", (session_id,), {}))
        return {"id": session_id, "agent_id": "shell", "status": "succeeded"}

    def get_session_events(self, session_id: str) -> dict[str, object]:
        self.calls.append(("get_session_events", (session_id,), {}))
        return {
            "events": [
                {
                    "id": 1,
                    "event_type": "policy_denied",
                    "message": "blocked",
                    "created_at": "2026-05-28 05:00:00",
                }
            ]
        }

    def get_session_timeline(
        self, session_id: str, event_type: str | None = None
    ) -> dict[str, object]:
        self.calls.append(("get_session_timeline", (session_id,), {"event_type": event_type}))
        return {
            "timeline": [
                {
                    "timestamp": "2026-05-30T00:00:00Z",
                    "type": event_type or "session_event",
                    "source": "session",
                    "message": "timeline event",
                }
            ]
        }

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
            ],
            "truncated": False,
        }

    def stop_session(self, session_id: str) -> dict[str, object]:
        self.calls.append(("stop_session", (session_id,), {}))
        return {"id": session_id, "status": "stopped"}

    def retry_session(self, session_id: str) -> dict[str, object]:
        self.calls.append(("retry_session", (session_id,), {}))
        return {"id": "s_2", "agent_id": "shell", "status": "queued"}

    def list_approvals(self, status=None, harness_id=None, limit=500):
        self.calls.append(
            ("list_approvals", (), {"status": status, "harness_id": harness_id, "limit": limit})
        )
        return {
            "approvals": [
                {
                    "id": "ap_1",
                    "source_session_id": "s_blocked",
                    "approved_session_id": None,
                    "agent_id": "shell",
                    "cwd": "/tmp/project",
                    "reason": "session.start requires approval",
                    "status": "pending",
                    "created_at": "2026-05-29 00:00:00",
                }
            ]
        }

    def show_approval(self, approval_id: str) -> dict[str, object]:
        self.calls.append(("show_approval", (approval_id,), {}))
        return {"id": approval_id, "agent_id": "shell", "status": "pending"}

    def approve_approval(self, approval_id: str) -> dict[str, object]:
        self.calls.append(("approve_approval", (approval_id,), {}))
        return {
            "id": approval_id,
            "agent_id": "shell",
            "status": "approved",
            "approved_session_id": "s_approved",
        }

    def reject_approval(self, approval_id: str, reason: str) -> dict[str, object]:
        self.calls.append(("reject_approval", (approval_id, reason), {}))
        return {"id": approval_id, "agent_id": "shell", "status": "rejected"}

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

    def list_skills(self) -> dict[str, object]:
        self.calls.append(("list_skills", (), {}))
        return {
            "skills": [
                {
                    "id": "reviewer",
                    "label": "Reviewer",
                    "enabled": True,
                    "source": "workspace",
                    "tags": ["review"],
                }
            ]
        }

    def show_skill(self, skill_id: str) -> dict[str, object]:
        self.calls.append(("show_skill", (skill_id,), {}))
        return {"id": skill_id, "label": "Reviewer", "enabled": True}

    def upsert_skill(self, skill_id: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("upsert_skill", (skill_id, payload), {}))
        return {"id": skill_id, **payload, "enabled": payload.get("enabled", True)}

    def disable_skill(self, skill_id: str) -> dict[str, object]:
        self.calls.append(("disable_skill", (skill_id,), {}))
        return {"id": skill_id, "label": "Reviewer", "enabled": False}

    def list_mcp_servers(self) -> dict[str, object]:
        self.calls.append(("list_mcp_servers", (), {}))
        return {
            "servers": [
                {
                    "id": "filesystem",
                    "label": "Filesystem MCP",
                    "enabled": True,
                    "transport": "stdio",
                    "command_preview": ["mcp-server"],
                }
            ]
        }

    def show_mcp_server(self, server_id: str) -> dict[str, object]:
        self.calls.append(("show_mcp_server", (server_id,), {}))
        return {"id": server_id, "label": "Filesystem MCP", "enabled": True}

    def upsert_mcp_server(self, server_id: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("upsert_mcp_server", (server_id, payload), {}))
        return {"id": server_id, **payload, "enabled": payload.get("enabled", True)}

    def disable_mcp_server(self, server_id: str) -> dict[str, object]:
        self.calls.append(("disable_mcp_server", (server_id,), {}))
        return {"id": server_id, "label": "Filesystem MCP", "enabled": False}

    def list_policies(self) -> dict[str, object]:
        self.calls.append(("list_policies", (), {}))
        return {
            "policies": [
                {
                    "agent_id": "shell",
                    "enabled": True,
                    "readonly": False,
                    "rate_limit_per_minute": 60,
                }
            ]
        }

    def show_policy(self, agent_id: str) -> dict[str, object]:
        self.calls.append(("show_policy", (agent_id,), {}))
        return {"agent_id": agent_id, "enabled": True, "readonly": False}

    def upsert_policy(self, agent_id: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("upsert_policy", (agent_id, payload), {}))
        return {"agent_id": agent_id, **payload}

    def evaluate_policy(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("evaluate_policy", (payload,), {}))
        return {
            "agent_id": payload["agent_id"],
            "decision": "allow",
            "reason": "policy allowed request",
        }

    def fleet_health(self) -> dict[str, object]:
        self.calls.append(("fleet_health", (), {}))
        return {
            "instances": [
                {
                    "agent_id": "shell",
                    "state": "up",
                    "version": "1.0.0",
                    "config_fingerprint": "abc",
                    "message": "OK",
                    "updated_at": "2026-05-29 00:00:00",
                }
            ]
        }

    def fleet_instance_health(self, agent_id: str) -> dict[str, object]:
        self.calls.append(("fleet_instance_health", (agent_id,), {}))
        return {
            "agent_id": agent_id,
            "state": "up",
            "version": "1.0.0",
            "config_fingerprint": "abc",
            "message": "OK",
            "updated_at": "2026-05-29 00:00:00",
        }

    def fleet_events(
        self,
        agent_id: str | None = None,
        event_type: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(("fleet_events", (), {"agent_id": agent_id, "event_type": event_type}))
        return {
            "events": [
                {
                    "id": 1,
                    "agent_id": "shell",
                    "event_type": "health_state_changed",
                    "message": "unknown -> up: OK",
                    "metadata": {},
                    "created_at": "2026-05-29 00:00:00",
                }
            ]
        }

    def fleet_capacity(self) -> dict[str, object]:
        self.calls.append(("fleet_capacity", (), {}))
        return {
            "running_sessions": 2,
            "max_running_sessions": 50,
            "registered_instances": 5,
            "max_registered_instances": 100,
            "at_session_limit": False,
            "at_instance_limit": False,
        }

    def fleet_probe(self) -> dict[str, object]:
        self.calls.append(("fleet_probe", (), {}))
        return {"probed": 3}

    def diagnostics_resources(self) -> dict[str, object]:
        self.calls.append(("diagnostics_resources", (), {}))
        return {
            "rss_bytes": 1024,
            "sqlite_wal_bytes": 0,
            "session_count": 1,
            "audit_event_count": 1,
            "fleet_event_count": 0,
        }

    def deprecate_skill(
        self,
        skill_id: str,
        *,
        reason: str = "",
        replacement_id: str | None = None,
        sunset_at: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "deprecate_skill",
                (skill_id,),
                {"reason": reason, "replacement_id": replacement_id, "sunset_at": sunset_at},
            )
        )
        return {
            "id": skill_id,
            "label": "Reviewer",
            "enabled": True,
            "deprecated": True,
            "deprecation_reason": reason,
            "replacement_id": replacement_id,
            "sunset_at": sunset_at,
        }

    def undeprecate_skill(self, skill_id: str) -> dict[str, object]:
        self.calls.append(("undeprecate_skill", (skill_id,), {}))
        return {"id": skill_id, "label": "Reviewer", "enabled": True, "deprecated": False}

    def deprecate_mcp_server(
        self,
        server_id: str,
        *,
        reason: str = "",
        replacement_id: str | None = None,
        sunset_at: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "deprecate_mcp_server",
                (server_id,),
                {"reason": reason, "replacement_id": replacement_id, "sunset_at": sunset_at},
            )
        )
        return {
            "id": server_id,
            "label": "FS",
            "enabled": True,
            "deprecated": True,
            "deprecation_reason": reason,
        }

    def undeprecate_mcp_server(self, server_id: str) -> dict[str, object]:
        self.calls.append(("undeprecate_mcp_server", (server_id,), {}))
        return {"id": server_id, "label": "FS", "enabled": True, "deprecated": False}

    def deprecate_policy(
        self,
        agent_id: str,
        *,
        reason: str = "",
        replacement_id: str | None = None,
        sunset_at: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "deprecate_policy",
                (agent_id,),
                {"reason": reason, "replacement_id": replacement_id, "sunset_at": sunset_at},
            )
        )
        return {
            "agent_id": agent_id,
            "enabled": True,
            "deprecated": True,
            "deprecation_reason": reason,
            "sunset_at": sunset_at,
        }

    def undeprecate_policy(self, agent_id: str) -> dict[str, object]:
        self.calls.append(("undeprecate_policy", (agent_id,), {}))
        return {"agent_id": agent_id, "enabled": True, "deprecated": False}

    def audit_events(
        self,
        domain: str | None = None,
        entity_id: str | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "audit_events",
                (),
                {
                    "domain": domain,
                    "entity_id": entity_id,
                    "event_type": event_type,
                    "limit": limit,
                },
            )
        )
        return {
            "events": [
                {
                    "id": 1,
                    "domain": "skill",
                    "entity_id": "reviewer",
                    "event_type": "skill_upserted",
                    "message": "upserted",
                    "metadata": {},
                    "created_at": "2026-05-29 00:00:00",
                }
            ]
        }

    def audit_policy_coverage(self) -> dict[str, object]:
        self.calls.append(("audit_policy_coverage", (), {}))
        return {
            "coverage": [
                {
                    "agent_id": "shell",
                    "has_policy": True,
                    "last_evaluated_at": "2026-05-29 00:00:00",
                    "recent_run_count": 3,
                    "runs_without_policy_evaluation": ["s_2"],
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
    assert fake.calls == [("run_session", ("shell", str(cwd.resolve()), "OK"), {"profile": None})]


def test_run_omits_cwd_when_not_provided(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["run", "shell", "--message", "OK"])

    assert result.exit_code == 0
    assert fake.calls == [("run_session", ("shell", None, "OK"), {"profile": None})]


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


def test_sessions_events_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["sessions", "events", "s_1"])

    assert result.exit_code == 0
    assert result.output == "1\tpolicy_denied\tblocked\t2026-05-28 05:00:00\n"
    assert fake.calls == [("get_session_events", ("s_1",), {})]


def test_sessions_timeline_passes_type_filter(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        cli.app,
        ["sessions", "timeline", "s_1", "--type", "log_chunk"],
    )

    assert result.exit_code == 0
    assert result.output == "2026-05-30T00:00:00Z\tlog_chunk\tsession\ttimeline event\n"
    assert fake.calls == [("get_session_timeline", ("s_1",), {"event_type": "log_chunk"})]


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


def test_approvals_list_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["approvals", "list"])

    assert result.exit_code == 0
    assert result.output == "ap_1\tshell\tpending\ts_blocked\t-\tsession.start requires approval\n"
    assert fake.calls == [
        ("list_approvals", (), {"status": None, "harness_id": None, "limit": 500})
    ]


def test_approvals_show_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["approvals", "show", "ap_1"])

    assert result.exit_code == 0
    assert '"id": "ap_1"' in result.output
    assert fake.calls == [("show_approval", ("ap_1",), {})]


def test_approvals_approve_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["approvals", "approve", "ap_1"])

    assert result.exit_code == 0
    assert '"approved_session_id": "s_approved"' in result.output
    assert fake.calls == [("approve_approval", ("ap_1",), {})]


def test_approvals_reject_sends_reason(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        cli.app,
        ["approvals", "reject", "ap_1", "--reason", "not needed"],
    )

    assert result.exit_code == 0
    assert '"status": "rejected"' in result.output
    assert fake.calls == [("reject_approval", ("ap_1", "not needed"), {})]


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


def test_skills_list_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["skills", "list"])

    assert result.exit_code == 0
    assert result.output == "reviewer\tReviewer\tenabled\tworkspace\treview\n"
    assert fake.calls == [("list_skills", (), {})]


def test_skills_show_prints_skill_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["skills", "show", "reviewer"])

    assert result.exit_code == 0
    assert '"id": "reviewer"' in result.output
    assert fake.calls == [("show_skill", ("reviewer",), {})]


def test_skills_upsert_sends_payload_and_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        cli.app,
        [
            "skills",
            "upsert",
            "reviewer",
            "--label",
            "Reviewer",
            "--description",
            "Review local changes",
            "--source",
            "workspace",
            "--entrypoint",
            "skills/reviewer/SKILL.md",
            "--tag",
            "review",
            "--tag",
            "local",
        ],
    )

    assert result.exit_code == 0
    assert '"id": "reviewer"' in result.output
    assert fake.calls == [
        (
            "upsert_skill",
            (
                "reviewer",
                {
                    "label": "Reviewer",
                    "description": "Review local changes",
                    "source": "workspace",
                    "entrypoint": "skills/reviewer/SKILL.md",
                    "tags": ["review", "local"],
                    "enabled": True,
                },
            ),
            {},
        )
    ]


def test_skills_disable_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["skills", "disable", "reviewer"])

    assert result.exit_code == 0
    assert '"enabled": false' in result.output
    assert fake.calls == [("disable_skill", ("reviewer",), {})]


def test_mcp_list_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["mcp", "list"])

    assert result.exit_code == 0
    assert result.output == "filesystem\tFilesystem MCP\tenabled\tstdio\tmcp-server\n"
    assert fake.calls == [("list_mcp_servers", (), {})]


def test_mcp_show_prints_server_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["mcp", "show", "filesystem"])

    assert result.exit_code == 0
    assert '"id": "filesystem"' in result.output
    assert fake.calls == [("show_mcp_server", ("filesystem",), {})]


def test_mcp_upsert_sends_env_keys_only(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        cli.app,
        [
            "mcp",
            "upsert",
            "filesystem",
            "--label",
            "Filesystem MCP",
            "--description",
            "Local metadata",
            "--transport",
            "stdio",
            "--command-preview",
            "mcp-server",
            "--command-preview",
            "--safe-flag",
            "--env-key",
            "MCP_TOKEN",
        ],
    )

    assert result.exit_code == 0
    assert '"id": "filesystem"' in result.output
    assert fake.calls == [
        (
            "upsert_mcp_server",
            (
                "filesystem",
                {
                    "label": "Filesystem MCP",
                    "description": "Local metadata",
                    "transport": "stdio",
                    "command_preview": ["mcp-server", "--safe-flag"],
                    "url": None,
                    "env_keys": ["MCP_TOKEN"],
                    "enabled": True,
                },
            ),
            {},
        )
    ]


def test_mcp_disable_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["mcp", "disable", "filesystem"])

    assert result.exit_code == 0
    assert '"enabled": false' in result.output
    assert fake.calls == [("disable_mcp_server", ("filesystem",), {})]


def test_policy_show_without_agent_lists_policies(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["policy", "show"])

    assert result.exit_code == 0
    assert result.output == "shell\tenabled\twrite\t60\n"
    assert fake.calls == [("list_policies", (), {})]


def test_policy_show_with_agent_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(cli.app, ["policy", "show", "shell"])

    assert result.exit_code == 0
    assert '"agent_id": "shell"' in result.output
    assert fake.calls == [("show_policy", ("shell",), {})]


def test_policy_set_sends_payload(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        cli.app,
        [
            "policy",
            "set",
            "shell",
            "--skill",
            "reviewer",
            "--mcp",
            "filesystem",
            "--tool",
            "read",
            "--approval-tool",
            "exec",
            "--model",
            "local-model",
            "--cwd-root",
            "/tmp/project",
            "--rate-limit",
            "20",
            "--readonly",
        ],
    )

    assert result.exit_code == 0
    assert '"agent_id": "shell"' in result.output
    assert fake.calls == [
        (
            "upsert_policy",
            (
                "shell",
                {
                    "enabled": True,
                    "readonly": True,
                    "allowed_skill_ids": ["reviewer"],
                    "allowed_mcp_server_ids": ["filesystem"],
                    "allowed_tool_names": ["read"],
                    "approval_required_tool_names": ["exec"],
                    "allowed_model_ids": ["local-model"],
                    "cwd_roots": ["/tmp/project"],
                    "rate_limit_per_minute": 20,
                },
            ),
            {},
        )
    ]


def test_policy_evaluate_prints_decision_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        cli.app,
        [
            "policy",
            "evaluate",
            "shell",
            "--skill",
            "reviewer",
            "--mcp",
            "filesystem",
            "--tool",
            "read",
            "--model",
            "local-model",
            "--cwd",
            "/tmp/project",
        ],
    )

    assert result.exit_code == 0
    assert '"decision": "allow"' in result.output
    assert fake.calls == [
        (
            "evaluate_policy",
            (
                {
                    "agent_id": "shell",
                    "skill_id": "reviewer",
                    "mcp_server_id": "filesystem",
                    "tool_name": "read",
                    "model_id": "local-model",
                    "cwd": "/tmp/project",
                },
            ),
            {},
        )
    ]


def test_make_client_uses_default_env_and_explicit_api(monkeypatch: Any) -> None:
    monkeypatch.delenv("AGENTIC_OS_API", raising=False)
    assert cli.make_client(None).base_url == "http://127.0.0.1:8767"

    monkeypatch.setenv("AGENTIC_OS_API", "http://env.example:9000/")
    assert cli.make_client(None).base_url == "http://env.example:9000"
    assert (
        cli.make_client("http://explicit.example:9001/").base_url == "http://explicit.example:9001"
    )


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
        if path.endswith("/events"):
            return FakeResponse({"events": []})
        return FakeResponse({"entries": []})

    def post(
        self,
        path: str,
        json: dict[str, object],
        params: dict[str, object] | None = None,
    ) -> "FakeResponse":
        request: dict[str, Any] = {
            "method": "POST",
            "base_url": self.base_url,
            "path": path,
            "json": json,
        }
        if params is not None:
            request["params"] = params
        self.requests.append(request)
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


def test_client_get_session_events_builds_expected_request(monkeypatch: Any) -> None:
    RecordingHttpxClient.requests = []
    monkeypatch.setattr("agentic_os.client.httpx.Client", RecordingHttpxClient)

    client = AgenticClient("http://api.example/")
    assert client.get_session_events("s_1") == {"events": []}

    assert RecordingHttpxClient.requests == [
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/sessions/s_1/events",
            "params": None,
        }
    ]


def test_client_get_session_timeline_builds_type_query(monkeypatch: Any) -> None:
    RecordingHttpxClient.requests = []
    monkeypatch.setattr("agentic_os.client.httpx.Client", RecordingHttpxClient)

    client = AgenticClient("http://api.example/")
    assert client.get_session_timeline("s_1", event_type="log_chunk") == {"entries": []}

    assert RecordingHttpxClient.requests == [
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/sessions/s_1/timeline",
            "params": {"event_type": "log_chunk"},
        }
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


def test_client_control_plane_methods_build_expected_requests(monkeypatch: Any) -> None:
    RecordingHttpxClient.requests = []
    monkeypatch.setattr("agentic_os.client.httpx.Client", RecordingHttpxClient)

    client = AgenticClient("http://api.example/")
    client.list_skills()
    client.show_skill("reviewer")
    client.upsert_skill("reviewer", {"label": "Reviewer"})
    client.disable_skill("reviewer")
    client.list_mcp_servers()
    client.show_mcp_server("filesystem")
    client.upsert_mcp_server("filesystem", {"label": "Filesystem MCP"})
    client.disable_mcp_server("filesystem")
    client.list_policies()
    client.show_policy("shell")
    client.upsert_policy("shell", {"allowed_tool_names": ["read"]})
    client.evaluate_policy({"agent_id": "shell", "tool_name": "read"})
    client.deprecate_skill("reviewer", reason="use v2", replacement_id="reviewer-v2")
    client.undeprecate_skill("reviewer")
    client.deprecate_mcp_server("filesystem", sunset_at="2026-06-30T00:00:00Z")
    client.undeprecate_mcp_server("filesystem")
    client.deprecate_policy("shell", reason="retire")
    client.undeprecate_policy("shell")
    client.diagnostics_resources()
    client.list_harnesses()
    client.show_harness("shell")
    client.harness_health("shell")
    client.harness_logs("shell")

    assert RecordingHttpxClient.requests == [
        {"method": "GET", "base_url": "http://api.example", "path": "/skills", "params": None},
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/skills/reviewer",
            "params": None,
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/skills/reviewer",
            "json": {"label": "Reviewer"},
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/skills/reviewer/disable",
            "json": {},
        },
        {"method": "GET", "base_url": "http://api.example", "path": "/mcp", "params": None},
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/mcp/filesystem",
            "params": None,
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/mcp/filesystem",
            "json": {"label": "Filesystem MCP"},
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/mcp/filesystem/disable",
            "json": {},
        },
        {"method": "GET", "base_url": "http://api.example", "path": "/policy", "params": None},
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/policy/shell",
            "params": None,
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/policy/shell",
            "json": {"allowed_tool_names": ["read"]},
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/policy/evaluate",
            "json": {"agent_id": "shell", "tool_name": "read"},
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/skills/reviewer/deprecate",
            "json": {"reason": "use v2", "replacement_id": "reviewer-v2"},
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/skills/reviewer/undeprecate",
            "json": {},
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/mcp/filesystem/deprecate",
            "json": {"sunset_at": "2026-06-30T00:00:00Z"},
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/mcp/filesystem/undeprecate",
            "json": {},
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/policy/shell/deprecate",
            "json": {"reason": "retire"},
        },
        {
            "method": "POST",
            "base_url": "http://api.example",
            "path": "/policy/shell/undeprecate",
            "json": {},
        },
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/diagnostics/resources",
            "params": None,
        },
        {"method": "GET", "base_url": "http://api.example", "path": "/harnesses", "params": None},
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/harnesses/shell",
            "params": None,
        },
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/harnesses/shell/health",
            "params": None,
        },
        {
            "method": "GET",
            "base_url": "http://api.example",
            "path": "/harnesses/shell/logs",
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
        lambda: client.get_session_events(unsafe_id),
        lambda: client.get_logs(unsafe_id),
        lambda: client.stop_session(unsafe_id),
        lambda: client.retry_session(unsafe_id),
        lambda: client.show_approval(unsafe_id),
        lambda: client.approve_approval(unsafe_id),
        lambda: client.reject_approval(unsafe_id, "no"),
        lambda: client.summarize_session(unsafe_id),
        lambda: client.show_session_summary(unsafe_id),
        lambda: client.create_memory_review(unsafe_id),
        lambda: client.approve_memory_review(unsafe_id),
        lambda: client.reject_memory_review(unsafe_id),
        lambda: client.show_skill(unsafe_id),
        lambda: client.upsert_skill(unsafe_id, {"label": "bad"}),
        lambda: client.disable_skill(unsafe_id),
        lambda: client.show_mcp_server(unsafe_id),
        lambda: client.upsert_mcp_server(unsafe_id, {"label": "bad"}),
        lambda: client.disable_mcp_server(unsafe_id),
        lambda: client.show_policy(unsafe_id),
        lambda: client.upsert_policy(unsafe_id, {}),
        lambda: client.show_harness(unsafe_id),
        lambda: client.harness_health(unsafe_id),
        lambda: client.harness_logs(unsafe_id),
        lambda: client.fleet_instance_health(unsafe_id),
        lambda: client.deprecate_skill(unsafe_id),
        lambda: client.undeprecate_skill(unsafe_id),
        lambda: client.deprecate_mcp_server(unsafe_id),
        lambda: client.undeprecate_mcp_server(unsafe_id),
        lambda: client.deprecate_policy(unsafe_id),
        lambda: client.undeprecate_policy(unsafe_id),
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
    assert runner.invoke(cli.app, ["approvals", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["memory", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["skills", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["mcp", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["policy", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["bench", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["fleet", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["audit", "--help"]).exit_code == 0


def test_fleet_health_list_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["fleet", "health"])
    assert result.exit_code == 0
    assert "shell\tup\t1.0.0\tOK" in result.output
    assert fake.calls == [("fleet_health", (), {})]


def test_fleet_health_show_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["fleet", "health", "shell"])
    assert result.exit_code == 0
    assert '"agent_id": "shell"' in result.output
    assert fake.calls == [("fleet_instance_health", ("shell",), {})]


def test_fleet_events_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["fleet", "events"])
    assert result.exit_code == 0
    assert "health_state_changed" in result.output
    assert fake.calls == [("fleet_events", (), {"agent_id": None, "event_type": None})]


def test_fleet_events_with_filters(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(
        cli.app, ["fleet", "events", "--agent", "shell", "--type", "config_drift_detected"]
    )
    assert result.exit_code == 0
    assert fake.calls == [
        ("fleet_events", (), {"agent_id": "shell", "event_type": "config_drift_detected"})
    ]


def test_fleet_capacity_prints_summary(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["fleet", "capacity"])
    assert result.exit_code == 0
    assert "sessions: 2/50" in result.output
    assert "instances: 5/100" in result.output
    assert fake.calls == [("fleet_capacity", (), {})]


def test_fleet_probe_prints_count(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["fleet", "probe"])
    assert result.exit_code == 0
    assert "Probed 3 instances" in result.output
    assert fake.calls == [("fleet_probe", (), {})]


def test_bench_slo_prints_summary_and_writes_report(monkeypatch: Any, tmp_path: Path) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    output = tmp_path / "report.json"
    test_api = "http://127.0.0.1:9876"

    result = CliRunner().invoke(
        cli.app,
        ["bench", "slo", "--api", test_api, "--iterations", "2", "--output", str(output)],
    )

    assert result.exit_code == 0
    assert "passed: yes" in result.output
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["api"] == test_api
    assert report["passed"] is True
    assert report["iterations"] == 2
    assert any(call[0] == "diagnostics_resources" for call in fake.calls)


def test_bench_slo_requires_explicit_test_daemon_api(monkeypatch: Any, tmp_path: Path) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    output = tmp_path / "report.json"

    result = CliRunner().invoke(cli.app, ["bench", "slo", "--output", str(output)])

    assert result.exit_code == 1
    assert "requires --api pointing at an explicit test daemon" in result.output
    assert output.exists() is False
    assert fake.calls == []


def test_skills_deprecate_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["skills", "deprecate", "reviewer"])
    assert result.exit_code == 0
    assert '"deprecated": true' in result.output
    assert fake.calls == [
        (
            "deprecate_skill",
            ("reviewer",),
            {"reason": "", "replacement_id": None, "sunset_at": None},
        )
    ]


def test_skills_deprecate_sends_metadata_flags(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(
        cli.app,
        [
            "skills",
            "deprecate",
            "reviewer",
            "--reason",
            "use reviewer-v2",
            "--replacement",
            "reviewer-v2",
            "--sunset",
            "2026-06-30T00:00:00Z",
        ],
    )
    assert result.exit_code == 0
    assert '"deprecation_reason": "use reviewer-v2"' in result.output
    assert fake.calls == [
        (
            "deprecate_skill",
            ("reviewer",),
            {
                "reason": "use reviewer-v2",
                "replacement_id": "reviewer-v2",
                "sunset_at": "2026-06-30T00:00:00Z",
            },
        )
    ]


def test_skills_undeprecate_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["skills", "undeprecate", "reviewer"])
    assert result.exit_code == 0
    assert '"deprecated": false' in result.output
    assert fake.calls == [("undeprecate_skill", ("reviewer",), {})]


def test_mcp_deprecate_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["mcp", "deprecate", "filesystem"])
    assert result.exit_code == 0
    assert '"deprecated": true' in result.output
    assert fake.calls == [
        (
            "deprecate_mcp_server",
            ("filesystem",),
            {"reason": "", "replacement_id": None, "sunset_at": None},
        )
    ]


def test_mcp_undeprecate_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["mcp", "undeprecate", "filesystem"])
    assert result.exit_code == 0
    assert '"deprecated": false' in result.output
    assert fake.calls == [("undeprecate_mcp_server", ("filesystem",), {})]


def test_policy_deprecate_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["policy", "deprecate", "shell"])
    assert result.exit_code == 0
    assert '"deprecated": true' in result.output
    assert fake.calls == [
        (
            "deprecate_policy",
            ("shell",),
            {"reason": "", "replacement_id": None, "sunset_at": None},
        )
    ]


def test_policy_undeprecate_prints_detail(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["policy", "undeprecate", "shell"])
    assert result.exit_code == 0
    assert '"deprecated": false' in result.output
    assert fake.calls == [("undeprecate_policy", ("shell",), {})]


def test_audit_events_prints_tab_separated_rows(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["audit", "events"])
    assert result.exit_code == 0
    assert "skill_upserted" in result.output
    assert fake.calls == [
        (
            "audit_events",
            (),
            {"domain": None, "entity_id": None, "event_type": None, "limit": 500},
        )
    ]


def test_audit_events_with_filters(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(
        cli.app,
        [
            "audit",
            "events",
            "--domain",
            "skill",
            "--entity",
            "reviewer",
            "--type",
            "skill_upserted",
            "--limit",
            "10",
        ],
    )
    assert result.exit_code == 0
    assert fake.calls == [
        (
            "audit_events",
            (),
            {
                "domain": "skill",
                "entity_id": "reviewer",
                "event_type": "skill_upserted",
                "limit": 10,
            },
        )
    ]


def test_audit_coverage_prints_summary(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["audit", "coverage"])
    assert result.exit_code == 0
    assert "shell" in result.output
    assert "policy=yes" in result.output
    assert "uncovered=1" in result.output
    assert fake.calls == [("audit_policy_coverage", (), {})]


def test_client_calls_harness_contract_endpoints(monkeypatch: Any) -> None:
    client = AgenticClient(base_url="http://example.com")
    responses: list[dict[str, object]] = [
        {"contracts": [], "count": 0},
        {"harness_id": "shell", "contract_version": "v2"},
    ]
    calls: list[tuple[str, dict[str, object] | None]] = []

    def fake_get(path: str, params: dict[str, object] | None = None) -> dict[str, object]:
        calls.append((path, params))
        return responses.pop(0)

    monkeypatch.setattr(client, "_get", fake_get)
    assert client.list_harness_contracts(version="v2")["contracts"] == []
    assert client.show_harness_contract("shell", version="v2")["harness_id"] == "shell"
    assert calls == [
        ("/harness-contracts", {"version": "v2"}),
        ("/harness-contracts/shell", {"version": "v2"}),
    ]


def test_cli_harness_contract_commands(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    runner = CliRunner()

    list_result = runner.invoke(cli.app, ["harness-contracts", "list", "--version", "v2"])
    assert list_result.exit_code == 0
    assert "v2" in list_result.output

    show_result = runner.invoke(cli.app, ["harness-contracts", "show", "shell", "--version", "v2"])
    assert show_result.exit_code == 0
    assert "v2" in show_result.output
    assert fake.calls == [
        ("list_harness_contracts", (), {"version": "v2"}),
        ("show_harness_contract", ("shell",), {"version": "v2"}),
    ]


def test_run_command_passes_profile_flag(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["run", "shell", "--message", "hello", "--profile", "default"],
    )
    assert result.exit_code == 0
    assert fake.calls[0] == (
        "run_session",
        ("shell", None, "hello"),
        {"profile": "default"},
    )


def test_usage_client_calls_api(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["usage", "summary", "--harness-id", "claude"])
    assert result.exit_code == 0
    assert fake.calls[0][0] == "usage_summary"


def test_deprecated_status_shown_in_skills_list(monkeypatch: Any) -> None:
    class DeprecatedSkillClient(FakeClient):
        def list_skills(self) -> dict[str, object]:
            self.calls.append(("list_skills", (), {}))
            return {
                "skills": [
                    {
                        "id": "old",
                        "label": "Old",
                        "enabled": True,
                        "deprecated": True,
                        "source": "local",
                        "tags": [],
                    },
                ]
            }

    fake = DeprecatedSkillClient()
    install_fake_client(monkeypatch, fake)
    result = CliRunner().invoke(cli.app, ["skills", "list"])
    assert result.exit_code == 0
    assert "deprecated" in result.output
