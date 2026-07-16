from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from agentic_os.audit import AuditStore
from agentic_os.backup_store import BackupStore
from agentic_os.change_service import ChangeService
from agentic_os.change_store import ChangeStore
from agentic_os.safe_edit import SafeEditEngine


@pytest.fixture
def home(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    root.mkdir()
    (root / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "command": "gh-mcp",
                        "args": ["--stdio"],
                        "env": {"GH_TOKEN": "sk-FAKE-SECRET"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (root / ".codex").mkdir()
    (root / ".codex" / "config.toml").write_text(
        'model = "gpt-5"\n\n[mcp_servers.context7]\ncommand = "npx"\n',
        encoding="utf-8",
    )
    return root


@pytest.fixture
def service(tmp_path: Path, home: Path) -> ChangeService:
    state_dir = tmp_path / ".agentic-os"
    state_dir.mkdir()
    database = state_dir / "agentic-os.db"
    audit_store = AuditStore(database)
    audit_store.init()
    change_store = ChangeStore(database)
    change_store.init()
    engine = SafeEditEngine(
        state_dir=state_dir,
        backup_store=BackupStore(state_dir),
        audit_store=audit_store,
    )
    return ChangeService(
        home=home,
        store=change_store,
        safe_edit_engine=engine,
    )


def sample_copy_request() -> dict[str, object]:
    return {
        "operation": "mcp.copy",
        "environment_id": "codex",
        "from_tool": "claude",
        "to_tool": "codex",
        "server": "github",
    }


def test_mcp_copy_preview_apply_verify_and_rollback(
    service: ChangeService,
    home: Path,
) -> None:
    target = home / ".codex" / "config.toml"
    before_bytes = target.read_bytes()

    plan = service.preview(sample_copy_request())

    assert plan.status == "previewed"
    assert plan.backup_ref is None
    assert plan.diff == {
        "operations": [{"op": "merge", "path": "mcp_servers.github"}]
    }

    verified = service.apply(plan.id)

    assert verified.status == "verified"
    assert verified.verification is not None
    assert verified.verification.status == "verified"
    assert verified.backup_ref
    document = tomllib.loads(target.read_text(encoding="utf-8"))
    assert document["mcp_servers"]["github"]["command"] == "gh-mcp"

    rolled_back = service.rollback(plan.id)

    assert rolled_back.status == "rolled_back"
    assert rolled_back.rollback is not None
    assert rolled_back.rollback["verified"] is True
    assert target.read_bytes() == before_bytes


def test_apply_persists_backup_reference_before_post_write_store_failure(
    service: ChangeService,
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = home / ".codex" / "config.toml"
    before_bytes = target.read_bytes()
    plan = service.preview(sample_copy_request())
    original_update = service.store.update
    update_count = 0

    def fail_second_update(candidate):
        nonlocal update_count
        update_count += 1
        if update_count == 2:
            raise RuntimeError("simulated post-write database failure")
        return original_update(candidate)

    monkeypatch.setattr(service.store, "update", fail_second_update)

    with pytest.raises(RuntimeError, match="post-write database failure"):
        service.apply(plan.id)

    persisted = service.get(plan.id)
    assert persisted.status == "applying"
    assert persisted.backup_ref == f"p_{plan.id.removeprefix('chg_')}"
    assert target.read_bytes() != before_bytes

    rolled_back = service.rollback(plan.id)

    assert rolled_back.status == "rolled_back"
    assert target.read_bytes() == before_bytes


def test_post_apply_verification_failure_stays_rollbackable(
    service: ChangeService,
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = home / ".codex" / "config.toml"
    before_bytes = target.read_bytes()
    plan = service.preview(sample_copy_request())
    original_post_mutation = service._post_mutation

    def fail_post_mutation(_operation: str) -> None:
        raise RuntimeError("simulated reload failure")

    monkeypatch.setattr(service, "_post_mutation", fail_post_mutation)

    partial = service.apply(plan.id)

    assert partial.status == "partial"
    assert partial.backup_ref
    assert partial.apply_result["applied"] is True
    assert partial.verification is not None
    assert partial.verification.status == "partial"
    assert partial.verification.checks[-1]["name"] == "post_apply_verification"
    assert partial.verification.checks[-1]["passed"] is False
    payload = service.payload_store.directory / f"{plan.id}.json"
    assert payload.exists()
    monkeypatch.setattr(service, "_post_mutation", original_post_mutation)

    rolled_back = service.rollback(plan.id)

    assert rolled_back.status == "rolled_back"
    assert target.read_bytes() == before_bytes


def test_apply_refuses_stale_preview(service: ChangeService, home: Path) -> None:
    plan = service.preview(sample_copy_request())
    target = home / ".codex" / "config.toml"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n[features]\nchanged = true\n",
        encoding="utf-8",
    )

    stale = service.apply(plan.id)

    assert stale.status == "stale"
    assert "github" not in tomllib.loads(target.read_text(encoding="utf-8"))["mcp_servers"]


def test_copy_plan_becomes_stale_when_source_changes(
    service: ChangeService,
    home: Path,
) -> None:
    plan = service.preview(sample_copy_request())
    source = home / ".claude.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["mcpServers"]["github"]["command"] = "different-command"
    source.write_text(json.dumps(payload), encoding="utf-8")

    stale = service.apply(plan.id)

    assert stale.status == "stale"


def test_persisted_plan_omits_command_url_and_secret_values(
    service: ChangeService,
) -> None:
    plan = service.preview(sample_copy_request())

    persisted = service.get(plan.id).model_dump_json()

    assert "gh-mcp" not in persisted
    assert "sk-FAKE-SECRET" not in persisted
    assert "command" not in persisted


def test_mcp_remove_round_trip(service: ChangeService, home: Path) -> None:
    target = home / ".codex" / "config.toml"
    before_bytes = target.read_bytes()
    plan = service.preview(
        {
            "operation": "mcp.remove",
            "environment_id": "codex",
            "server": "context7",
        }
    )

    assert service.apply(plan.id).status == "verified"
    assert "context7" not in tomllib.loads(target.read_text(encoding="utf-8"))["mcp_servers"]
    assert service.rollback(plan.id).status == "rolled_back"
    assert target.read_bytes() == before_bytes


@pytest.mark.parametrize(
    "operation",
    [
        "catalog.patch",
        "config.patch",
        "harness_config.patch",
        "profile.patch",
        "registry.patch",
    ],
)
def test_supported_operation_round_trip(
    tmp_path: Path,
    home: Path,
    operation: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    registry_path = tmp_path / "agents.toml"
    _write_registry(registry_path)
    operation_service = _make_service(
        tmp_path,
        home,
        registry_path=registry_path,
    )
    request, target = _operation_request(operation, repo, home, registry_path)
    before_bytes = target.read_bytes()

    plan = operation_service.preview(request)

    assert plan.status == "previewed"
    assert operation_service.apply(plan.id).status == "verified"
    assert target.read_bytes() != before_bytes
    assert operation_service.rollback(plan.id).status == "rolled_back"
    assert target.read_bytes() == before_bytes


def test_sensitive_payload_is_private_durable_and_not_in_plan(
    tmp_path: Path,
    home: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    registry_path = tmp_path / "agents.toml"
    _write_registry(registry_path)
    first_service = _make_service(tmp_path, home, registry_path=registry_path)
    request, _target = _operation_request(
        "config.patch",
        repo,
        home,
        registry_path,
    )

    plan = first_service.preview(request)
    database_bytes = (tmp_path / ".agentic-os" / "agentic-os.db").read_bytes()
    payload_path = tmp_path / ".agentic-os" / "change-payloads" / f"{plan.id}.json"

    assert b"sk-VERY-SECRET" not in database_bytes
    assert "sk-VERY-SECRET" not in plan.model_dump_json()
    assert payload_path.stat().st_mode & 0o777 == 0o600

    restarted_service = _make_service(tmp_path, home, registry_path=registry_path)
    applied = restarted_service.apply(plan.id)

    assert applied.status == "verified"
    assert payload_path.exists() is False


def _make_service(
    tmp_path: Path,
    home: Path,
    *,
    registry_path: Path | None = None,
) -> ChangeService:
    state_dir = tmp_path / ".agentic-os"
    state_dir.mkdir(exist_ok=True)
    database = state_dir / "agentic-os.db"
    audit_store = AuditStore(database)
    audit_store.init()
    change_store = ChangeStore(database)
    change_store.init()
    return ChangeService(
        home=home,
        store=change_store,
        safe_edit_engine=SafeEditEngine(
            state_dir=state_dir,
            backup_store=BackupStore(state_dir),
            audit_store=audit_store,
        ),
        registry_path=registry_path,
    )


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


def _operation_request(
    operation: str,
    repo: Path,
    home: Path,
    registry_path: Path,
) -> tuple[dict[str, object], Path]:
    if operation == "catalog.patch":
        target = repo / ".claude" / "settings.json"
        target.parent.mkdir(parents=True)
        target.write_text("{}", encoding="utf-8")
        return (
            {
                "operation": operation,
                "environment_id": "claude",
                "cwd": str(repo),
                "ops": [
                    {
                        "op": "enable_mcp_server",
                        "scope": "project",
                        "name": "demo",
                        "config": {
                            "command": "demo-mcp",
                            "env": {"API_TOKEN": "sk-VERY-SECRET"},
                        },
                    }
                ],
            },
            target,
        )
    if operation == "config.patch":
        target = repo / ".agentic-os" / "config.toml"
        target.parent.mkdir(parents=True)
        target.write_text("[daemon]\nport = 8767\n", encoding="utf-8")
        return (
            {
                "operation": operation,
                "environment_id": "agentic_os",
                "scope": "project",
                "cwd": str(repo),
                "ops": [
                    {
                        "op": "merge",
                        "path": "daemon.credentials",
                        "value": {"api_token": "sk-VERY-SECRET"},
                    }
                ],
            },
            target,
        )
    if operation == "harness_config.patch":
        target = repo / ".claude" / "settings.json"
        target.parent.mkdir(parents=True)
        target.write_text('{"model":"before"}', encoding="utf-8")
        return (
            {
                "operation": operation,
                "environment_id": "claude",
                "scope": "project",
                "cwd": str(repo),
                "ops": [{"op": "merge", "path": "model", "value": "after"}],
            },
            target,
        )
    if operation == "profile.patch":
        target = repo / ".agentic-os" / "profiles.toml"
        target.parent.mkdir(parents=True)
        target.write_text(
            """
[run_profiles.base]
harness_id = "shell"
provider = "local"
model = "local"
""",
            encoding="utf-8",
        )
        return (
            {
                "operation": operation,
                "environment_id": "agentic_os",
                "action": "upsert",
                "scope": "local",
                "cwd": str(repo),
                "profile": {
                    "name": "secure",
                    "harness_id": "shell",
                    "provider": "local",
                    "model": "local",
                    "default_env": {"API_TOKEN": "sk-VERY-SECRET"},
                },
            },
            target,
        )
    if operation == "registry.patch":
        return (
            {
                "operation": operation,
                "environment_id": "agentic_os",
                "action": "upsert",
                "agent": {
                    "id": "demo",
                    "label": "Demo",
                    "command": ["/usr/bin/printf", "{{message}}"],
                    "cwd_mode": "optional",
                    "env": {"API_TOKEN": "sk-VERY-SECRET"},
                    "health_command": ["/usr/bin/true"],
                    "version_command": ["/usr/bin/printf", "1.0"],
                    "config_fingerprint_command": ["/usr/bin/printf", "stable"],
                    "config_path": "~/.demo",
                    "default_provider": "demo",
                },
            },
            registry_path,
        )
    raise AssertionError(f"unsupported test operation: {operation}")
