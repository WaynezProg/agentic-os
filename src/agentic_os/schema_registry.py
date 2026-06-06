from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

_SCHEMAS_PKG = "agentic_os.schemas"

# path prefix whitelist per harness/kind
_PATH_WHITELIST: dict[tuple[str, str], tuple[str, ...]] = {
    ("claude", "mcp_server"): ("mcpServers",),
    ("claude", "hook"): ("hooks",),
    ("cursor", "mcp_server"): ("mcpServers",),
    ("cursor", "hook"): ("hooks",),
    ("codex", "mcp_server"): ("mcp_servers",),
    ("opencode", "mcp_server"): ("mcpServers",),
    ("qwen", "mcp_server"): ("mcpServers",),
    ("openclaw", "mcp_server"): ("mcp_servers",),
    ("hermes", "mcp_server"): ("mcp_servers",),
    ("agentic_os", "config"): ("harness", "daemon", "fleet"),
}


class SchemaRegistry:
    def validate_document(self, harness: str, kind: str, doc: dict[str, Any]) -> list[str]:
        schema = _load_schema(harness, kind)
        if schema is None:
            return [f"no schema for {harness}/{kind}"]
        validator = Draft202012Validator(schema)
        return [f"{e.json_path}: {e.message}" for e in sorted(validator.iter_errors(doc), key=str)]

    def is_path_allowed(self, harness: str, kind: str, path: str) -> bool:
        prefixes = _PATH_WHITELIST.get((harness, kind), ())
        if not prefixes:
            return False
        top = path.split(".")[0].split("[")[0]
        return any(top == prefix or path.startswith(f"{prefix}.") for prefix in prefixes)


@lru_cache(maxsize=64)
def _load_schema(harness: str, kind: str) -> dict[str, Any] | None:
    filename = f"{kind}@v1.json"
    try:
        raw = resources.files(_SCHEMAS_PKG).joinpath(harness, filename).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, TypeError):
        return None
    return json.loads(raw)
