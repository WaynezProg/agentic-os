from __future__ import annotations

from pathlib import Path

from agentic_os.toml_io import atomic_write_toml, load_toml


def test_atomic_write_toml_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    payload = {"mcp_servers": {"github": {"command": "npx", "args": ["-y", "mcp"]}}}
    atomic_write_toml(path, payload)
    assert load_toml(path) == payload
