from __future__ import annotations

import os
import tomllib
import uuid
from pathlib import Path
from typing import Any

import tomli_w


def serialize_toml(payload: dict[str, Any]) -> str:
    return tomli_w.dumps(payload)


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def atomic_write_toml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(serialize_toml(payload), encoding="utf-8")
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
