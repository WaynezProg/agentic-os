from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class PatchIndexEntry:
    patch_id: str
    harness_id: str
    cwd: str
    target_kind: str
    surface_id: str | None
    backup_kind: str
    backup_paths: list[str]
    target_path: str
    source: str
    created_at: str
    target_existed_before: bool = True
    rolled_back_at: str | None = None
    rollback_of: str | None = None


class BackupStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.patches_dir = state_dir / "patches"
        self.index_path = self.patches_dir / "index.jsonl"

    def create_snapshot(
        self,
        *,
        patch_id: str,
        harness_id: str,
        cwd: Path,
        target_path: Path,
        target_kind: str,
        source: str,
        surface_id: str | None = None,
    ) -> PatchIndexEntry:
        self.patches_dir.mkdir(parents=True, exist_ok=True)
        rel = target_path.name
        backup_dir = self.patches_dir / patch_id / "before"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / rel
        if target_path.exists():
            shutil.copy2(target_path, backup_file)
        else:
            backup_file.write_text("", encoding="utf-8")
        entry = PatchIndexEntry(
            patch_id=patch_id,
            harness_id=harness_id,
            cwd=str(cwd.resolve()),
            target_kind=target_kind,
            surface_id=surface_id,
            backup_kind="snapshot",
            backup_paths=[str(backup_file)],
            target_path=str(target_path),
            source=source,
            created_at=datetime.now(UTC).isoformat(),
            target_existed_before=target_path.exists(),
        )
        self._append_index(entry)
        return entry

    def create_sidecar(self, target_path: Path) -> Path:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        sidecar = target_path.with_name(f"{target_path.name}.bak.{ts}")
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            shutil.copy2(target_path, sidecar)
        else:
            sidecar.write_text("", encoding="utf-8")
        return sidecar

    def create_sidecar_indexed(
        self,
        *,
        patch_id: str,
        harness_id: str,
        cwd: Path,
        target_path: Path,
        target_kind: str,
        source: str,
        surface_id: str | None = None,
    ) -> PatchIndexEntry:
        sidecar = self.create_sidecar(target_path)
        entry = PatchIndexEntry(
            patch_id=patch_id,
            harness_id=harness_id,
            cwd=str(cwd.resolve()),
            target_kind=target_kind,
            surface_id=surface_id,
            backup_kind="sidecar",
            backup_paths=[str(sidecar)],
            target_path=str(target_path),
            source=source,
            created_at=datetime.now(UTC).isoformat(),
            target_existed_before=target_path.exists(),
        )
        self._append_index(entry)
        return entry

    def restore(self, entry: PatchIndexEntry) -> None:
        target = Path(entry.target_path)
        backup = Path(entry.backup_paths[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not entry.target_existed_before:
            if target.exists():
                target.unlink()
            return
        shutil.copy2(backup, target)

    def get(self, patch_id: str) -> PatchIndexEntry | None:
        if not self.index_path.exists():
            return None
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if data["patch_id"] == patch_id:
                return _entry_from_index_data(data)
        return None

    def list_entries(
        self, *, harness_id: str | None = None, cwd: str | None = None, limit: int = 50
    ) -> list[PatchIndexEntry]:
        if not self.index_path.exists():
            return []
        entries: list[PatchIndexEntry] = []
        for line in reversed(self.index_path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            entry = _entry_from_index_data(json.loads(line))
            if harness_id and entry.harness_id != harness_id:
                continue
            if cwd and entry.cwd != str(Path(cwd).resolve()):
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break
        return entries

    def mark_rolled_back(self, patch_id: str) -> None:
        if not self.index_path.exists():
            return
        lines: list[str] = []
        now = datetime.now(UTC).isoformat()
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if data["patch_id"] == patch_id:
                data["rolled_back_at"] = now
            lines.append(json.dumps(data))
        self.index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _append_index(self, entry: PatchIndexEntry) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "patch_id": entry.patch_id,
            "harness_id": entry.harness_id,
            "cwd": entry.cwd,
            "target_kind": entry.target_kind,
            "surface_id": entry.surface_id,
            "backup_kind": entry.backup_kind,
            "backup_paths": entry.backup_paths,
            "target_path": entry.target_path,
            "source": entry.source,
            "created_at": entry.created_at,
            "target_existed_before": entry.target_existed_before,
            "rolled_back_at": entry.rolled_back_at,
            "rollback_of": entry.rollback_of,
        }
        with self.index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")


def _entry_from_index_data(data: dict[str, object]) -> PatchIndexEntry:
    if "target_existed_before" not in data:
        data = {**data, "target_existed_before": True}
    return PatchIndexEntry(**data)  # type: ignore[arg-type]
