from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class ChangePayloadStore:
    def __init__(self, state_dir: Path) -> None:
        self.directory = state_dir / "change-payloads"

    def write(self, change_id: str, payload: dict[str, object]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        target = self._path(change_id)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                prefix=f".{change_id}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.chmod(0o600)
            temporary_path.replace(target)
            target.chmod(0o600)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def read(self, change_id: str) -> dict[str, object] | None:
        path = self._path(change_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("change payload must be an object")
        return payload

    def delete(self, change_id: str) -> None:
        self._path(change_id).unlink(missing_ok=True)

    def _path(self, change_id: str) -> Path:
        if not change_id.startswith("chg_") or not change_id[4:].isalnum():
            raise ValueError("invalid change id")
        return self.directory / f"{change_id}.json"
