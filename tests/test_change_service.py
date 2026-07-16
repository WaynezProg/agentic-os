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
