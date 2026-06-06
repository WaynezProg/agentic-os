from pathlib import Path

from agentic_os.backup_store import BackupStore


def test_snapshot_backup_and_restore(tmp_path: Path) -> None:
    state_dir = tmp_path / ".agentic-os"
    target = tmp_path / "repo" / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"model": "before"}', encoding="utf-8")
    store = BackupStore(state_dir)
    entry = store.create_snapshot(
        patch_id="p_test1",
        harness_id="claude",
        cwd=tmp_path / "repo",
        target_path=target,
        target_kind="surface",
        source="test",
    )
    target.write_text('{"model": "after"}', encoding="utf-8")
    store.restore(entry)
    assert target.read_text(encoding="utf-8") == '{"model": "before"}'


def test_restore_preserves_empty_file_when_it_existed_before(tmp_path: Path) -> None:
    state_dir = tmp_path / ".agentic-os"
    target = tmp_path / "repo" / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    store = BackupStore(state_dir)
    entry = store.create_snapshot(
        patch_id="p_empty",
        harness_id="claude",
        cwd=tmp_path / "repo",
        target_path=target,
        target_kind="surface",
        source="test",
    )
    assert entry.target_existed_before is True
    target.write_text('{"model": "after"}', encoding="utf-8")
    store.restore(entry)
    assert target.read_text(encoding="utf-8") == ""


def test_restore_deletes_file_created_by_patch(tmp_path: Path) -> None:
    state_dir = tmp_path / ".agentic-os"
    target = tmp_path / "repo" / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    store = BackupStore(state_dir)
    entry = store.create_snapshot(
        patch_id="p_new",
        harness_id="claude",
        cwd=tmp_path / "repo",
        target_path=target,
        target_kind="surface",
        source="test",
    )
    assert entry.target_existed_before is False
    target.write_text('{"model": "after"}', encoding="utf-8")
    store.restore(entry)
    assert not target.exists()
