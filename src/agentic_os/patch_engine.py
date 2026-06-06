from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


@dataclass(frozen=True)
class PatchOp:
    op: str
    path: str
    value: Any | None = None


class PatchEngine:
    @staticmethod
    def apply(doc: dict[str, Any], ops: list[PatchOp]) -> dict[str, Any]:
        result = copy.deepcopy(doc)
        for item in ops:
            if item.op == "merge":
                if item.value is None:
                    msg = "merge op requires value"
                    raise ValueError(msg)
                _set_at_path(result, item.path, item.value, merge=True)
            elif item.op == "remove":
                _delete_at_path(result, item.path)
            else:
                msg = f"unsupported op: {item.op}"
                raise ValueError(msg)
        return result

    @staticmethod
    def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        added: dict[str, Any] = {}
        modified: dict[str, Any] = {}
        removed: dict[str, Any] = {}
        all_keys = set(before) | set(after)
        for key in sorted(all_keys):
            if key not in before:
                added[key] = after[key]
            elif key not in after:
                removed[key] = before[key]
            elif before[key] != after[key]:
                modified[key] = {"before": before[key], "after": after[key]}
        return {"added": added, "modified": modified, "removed": removed}


def _parse_tokens(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for match in _PATH_TOKEN.finditer(path):
        if match.group(1) is not None:
            tokens.append(match.group(1))
        else:
            tokens.append(int(match.group(2)))
    return tokens


def _deep_merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, overlay_value in overlay.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(overlay_value, dict):
            result[key] = _deep_merge_dict(current, overlay_value)
        else:
            result[key] = copy.deepcopy(overlay_value)
    return result


def _set_at_path(doc: dict[str, Any], path: str, value: Any, *, merge: bool) -> None:
    tokens = _parse_tokens(path)
    if not tokens:
        msg = "empty path"
        raise ValueError(msg)
    cursor: Any = doc
    for token in tokens[:-1]:
        cursor = _descend(cursor, token, create=True)
    last = tokens[-1]
    existing = cursor.get(last) if isinstance(cursor, dict) else None
    if merge and isinstance(existing, dict) and isinstance(value, dict):
        cursor[last] = _deep_merge_dict(existing, value)
        return
    if merge and isinstance(existing, list) and isinstance(value, list):
        cursor[last] = copy.deepcopy(existing) + copy.deepcopy(value)
        return
    cursor[last] = copy.deepcopy(value)


def _delete_at_path(doc: dict[str, Any], path: str) -> None:
    tokens = _parse_tokens(path)
    if not tokens:
        return
    cursor: Any = doc
    for token in tokens[:-1]:
        cursor = _descend(cursor, token, create=False)
        if cursor is None:
            return
    last = tokens[-1]
    if isinstance(cursor, dict):
        cursor.pop(last, None)
    elif isinstance(cursor, list) and isinstance(last, int) and 0 <= last < len(cursor):
        cursor.pop(last)


def _descend(cursor: Any, token: str | int, *, create: bool) -> Any:
    if isinstance(token, int):
        if not isinstance(cursor, list):
            msg = f"expected list at index access, got {type(cursor)}"
            raise TypeError(msg)
        while create and len(cursor) <= token:
            cursor.append({})
        return cursor[token]
    if not isinstance(cursor, dict):
        msg = f"expected dict at key {token!r}, got {type(cursor)}"
        raise TypeError(msg)
    if create and token not in cursor:
        cursor[token] = {}
    return cursor[token]
