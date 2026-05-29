from __future__ import annotations

import os
import resource
import sys
from pathlib import Path


def resource_snapshot(state_dir: Path, sqlite_path: Path) -> dict[str, int]:
    return {
        "pid": os.getpid(),
        "rss_bytes": _rss_bytes(),
        "state_dir_bytes": _dir_size(state_dir),
        "sqlite_db_bytes": _file_size(sqlite_path),
        "sqlite_wal_bytes": _file_size(Path(f"{sqlite_path}-wal")),
    }


def _rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    value = max(int(usage.ru_maxrss), 0)
    if sys.platform == "darwin":
        return value
    return value * 1024


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
