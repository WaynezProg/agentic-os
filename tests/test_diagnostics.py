from __future__ import annotations

from pathlib import Path

from agentic_os.diagnostics import resource_snapshot


def test_resource_snapshot_reports_sqlite_file_sizes(tmp_path: Path) -> None:
    db = tmp_path / "agentic-os.db"
    db.write_bytes(b"1234")
    wal = tmp_path / "agentic-os.db-wal"
    wal.write_bytes(b"12")

    snap = resource_snapshot(tmp_path, db)

    assert snap["sqlite_db_bytes"] == 4
    assert snap["sqlite_wal_bytes"] == 2
    assert snap["state_dir_bytes"] >= 6
    assert snap["pid"] > 0
    assert snap["rss_bytes"] >= 0
