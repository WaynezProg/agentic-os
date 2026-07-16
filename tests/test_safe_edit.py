import json
from pathlib import Path

import pytest

from agentic_os.audit import AuditStore
from agentic_os.backup_store import BackupStore
from agentic_os.catalog import resolve_standalone_surface_path
from agentic_os.patch_engine import PatchOp
from agentic_os.safe_edit import PatchTarget, SafeEditEngine


def test_dry_run_does_not_write_file(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    claude = repo / ".claude"
    claude.mkdir(parents=True)
    settings = claude / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    state_dir = tmp_path / ".agentic-os"
    state_dir.mkdir(parents=True)
    engine = SafeEditEngine(
        state_dir=state_dir,
        backup_store=BackupStore(state_dir),
        audit_store=AuditStore(state_dir / "agentic-os.db"),
    )
    engine.audit_store.init()
    target = PatchTarget(
        harness_id="claude",
        cwd=repo,
        scope="project",
        target_kind="surface",
        kind="mcp_server",
        file_path=settings,
        file_format="json",
    )
    ops = [PatchOp(op="merge", path="mcpServers.gh", value={"command": "npx"})]
    result = engine.apply(target, ops, source="test", dry_run=True)
    assert result.applied is False
    assert json.loads(settings.read_text(encoding="utf-8")) == {}


def test_apply_writes_and_rollback_restores(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    state_dir = tmp_path / ".agentic-os"
    state_dir.mkdir(parents=True)
    engine = SafeEditEngine(
        state_dir=state_dir,
        backup_store=BackupStore(state_dir),
        audit_store=AuditStore(state_dir / "agentic-os.db"),
    )
    engine.audit_store.init()
    target = PatchTarget(
        harness_id="claude",
        cwd=repo,
        scope="project",
        target_kind="surface",
        kind="mcp_server",
        file_path=settings,
        file_format="json",
        surface_id="mcp_server:gh@project",
    )
    ops = [PatchOp(op="merge", path="mcpServers.gh", value={"command": "npx"})]
    applied = engine.apply(target, ops, source="test", dry_run=False)
    assert "gh" in json.loads(settings.read_text(encoding="utf-8"))["mcpServers"]
    engine.rollback(applied.patch_id, source="test")
    assert json.loads(settings.read_text(encoding="utf-8")) == {}


def test_upsert_skill_creates_file_with_sidecar_backup(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    monkeypatch.setenv("HOME", str(home))
    state_dir = tmp_path / ".agentic-os"
    state_dir.mkdir(parents=True)
    engine = SafeEditEngine(
        state_dir=state_dir,
        backup_store=BackupStore(state_dir),
        audit_store=AuditStore(state_dir / "agentic-os.db"),
    )
    engine.audit_store.init()
    skill_path = resolve_standalone_surface_path(
        "claude", "project", "skill", "demo-skill", repo
    )
    result = engine.apply_standalone(
        harness_id="claude",
        cwd=repo,
        scope="project",
        file_path=skill_path,
        content="# Demo Skill\n",
        surface_id="skill:demo-skill@project",
        source="test",
        dry_run=False,
    )
    assert result.applied is True
    assert skill_path.read_text(encoding="utf-8") == "# Demo Skill\n"
    entry = engine.backup_store.get(result.patch_id)
    assert entry is not None
    assert entry.backup_kind == "sidecar"
    sidecar = Path(entry.backup_paths[0])
    assert sidecar.exists()
    assert sidecar.name.startswith("SKILL.md.bak.")


def test_rollback_restores_skill_file(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    monkeypatch.setenv("HOME", str(home))
    state_dir = tmp_path / ".agentic-os"
    state_dir.mkdir(parents=True)
    engine = SafeEditEngine(
        state_dir=state_dir,
        backup_store=BackupStore(state_dir),
        audit_store=AuditStore(state_dir / "agentic-os.db"),
    )
    engine.audit_store.init()
    skill_path = resolve_standalone_surface_path(
        "claude", "project", "skill", "demo-skill", repo
    )
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("# Original\n", encoding="utf-8")
    applied = engine.apply_standalone(
        harness_id="claude",
        cwd=repo,
        scope="project",
        file_path=skill_path,
        content="# Updated\n",
        surface_id="skill:demo-skill@project",
        source="test",
        dry_run=False,
    )
    assert skill_path.read_text(encoding="utf-8") == "# Updated\n"
    engine.rollback(applied.patch_id, source="test")
    assert skill_path.read_text(encoding="utf-8") == "# Original\n"


def test_observe_target_refuses_malformed_json(tmp_path: Path) -> None:
    engine, target = _engine_and_target(tmp_path, file_format="json", content="{broken")

    with pytest.raises(ValueError, match="config parse error"):
        engine.observe_target(target)


def test_observe_target_refuses_malformed_toml(tmp_path: Path) -> None:
    engine, target = _engine_and_target(tmp_path, file_format="toml", content="broken = [")

    with pytest.raises(ValueError, match="config parse error"):
        engine.observe_target(target)


def test_observe_target_returns_hash_mtime_and_document(tmp_path: Path) -> None:
    engine, target = _engine_and_target(tmp_path, file_format="json", content="{}")

    observed = engine.observe_target(target)

    assert observed.exists is True
    assert observed.content_sha256
    assert observed.mtime_ns == target.file_path.stat().st_mtime_ns
    assert observed.document == {}


def test_apply_refuses_malformed_document(tmp_path: Path) -> None:
    engine, target = _engine_and_target(tmp_path, file_format="json", content="{broken")

    with pytest.raises(ValueError, match="config parse error"):
        engine.apply(
            target,
            [PatchOp(op="merge", path="mcpServers.gh", value={"command": "npx"})],
            source="test",
        )

    assert target.file_path.read_text(encoding="utf-8") == "{broken"


def _engine_and_target(
    tmp_path: Path,
    *,
    file_format: str,
    content: str,
) -> tuple[SafeEditEngine, PatchTarget]:
    state_dir = tmp_path / ".agentic-os"
    state_dir.mkdir(parents=True)
    audit_store = AuditStore(state_dir / "agentic-os.db")
    audit_store.init()
    engine = SafeEditEngine(
        state_dir=state_dir,
        backup_store=BackupStore(state_dir),
        audit_store=audit_store,
    )
    suffix = "json" if file_format == "json" else "toml"
    file_path = tmp_path / f"config.{suffix}"
    file_path.write_text(content, encoding="utf-8")
    target = PatchTarget(
        harness_id="codex",
        cwd=tmp_path,
        scope="user",
        target_kind="config",
        kind="mcp_server",
        file_path=file_path,
        file_format=file_format,
    )
    return engine, target
