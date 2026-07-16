from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


def serialize_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write ``payload`` as pretty JSON to ``path``.

    The temp file name is unique per write (pid + uuid) so concurrent writers
    targeting the same path never collide on the staging file. Without this,
    two threads sharing a fixed ``.{name}.tmp`` would race on ``replace`` and
    one would raise ``FileNotFoundError`` (its temp file already renamed away).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(serialize_json(payload), encoding="utf-8")
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
