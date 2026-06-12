"""Tests for P42 MCP alignment adapters and patch builders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_os.mcp_alignment import (
    build_copy_patch,
    build_remove_patch,
    from_canonical,
    read_server_def,
    read_server_names,
    summarize_def,
    target_config_parse_error,
    to_canonical,
)


def _make_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"

    (home / ".claude").mkdir(parents=True)
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "command": "gh-mcp",
                        "args": ["--stdio"],
                        "env": {"GH_TOKEN": "sk-FAKE-SECRET"},
                        "customField": "keepme",
                    },
                    "linear": {"url": "https://mcp.linear.app/sse"},
                },
                "otherTopLevel": {"untouched": True},
            }
        ),
        encoding="utf-8",
    )

    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "config.toml").write_text(
        'model = "gpt-5"\n\n[mcp_servers.context7]\ncommand = "npx"\nargs = ["-y", "context7-mcp"]\n',
        encoding="utf-8",
    )

    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.json").write_text(
        json.dumps(
            {
                "mcp": {
                    "chrome": {
                        "type": "local",
                        "command": ["npx", "-y", "chrome-mcp"],
                        "environment": {"CHROME_KEY": "ck-FAKE"},
                        "enabled": True,
                    },
                    "hermes": {"type": "remote", "url": "http://localhost:8893/sse"},
                }
            }
        ),
        encoding="utf-8",
    )

    (home / ".gemini").mkdir(parents=True)
    (home / ".gemini" / "settings.json").write_text(
        json.dumps({"mcpServers": {"context7": {"command": "npx", "args": ["c7"]}}}),
        encoding="utf-8",
    )

    (home / ".qwen").mkdir(parents=True)
    (home / ".qwen" / "settings.json").write_text(
        json.dumps({"mcpServers": {}}), encoding="utf-8"
    )

    (home / ".cursor").mkdir(parents=True)
    (home / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"codegraph": {"command": "cg-mcp"}}}),
        encoding="utf-8",
    )

    return home


def test_read_server_names_per_tool(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    assert read_server_names("claude", home) == ["github", "linear"]
    assert read_server_names("codex", home) == ["context7"]
    assert read_server_names("opencode", home) == ["chrome", "hermes"]
    assert read_server_names("gemini", home) == ["context7"]
    assert read_server_names("qwen", home) == []
    assert read_server_names("cursor", home) == ["codegraph"]


def test_canonical_roundtrip_mcpservers_family(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    raw = read_server_def("claude", "github", home)
    assert raw is not None
    canon = to_canonical("claude", raw)
    assert canon.transport == "stdio"
    assert canon.command == "gh-mcp"
    assert canon.args == ["--stdio"]
    assert canon.env == {"GH_TOKEN": "sk-FAKE-SECRET"}
    out = from_canonical("gemini", canon)
    assert out["command"] == "gh-mcp"
    assert out["args"] == ["--stdio"]
    assert out["env"] == {"GH_TOKEN": "sk-FAKE-SECRET"}
    # extras carried within the mcpServers family
    assert out["customField"] == "keepme"


def test_canonical_opencode_array_command_both_ways(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    raw = read_server_def("opencode", "chrome", home)
    canon = to_canonical("opencode", raw)
    assert canon.transport == "stdio"
    assert canon.command == "npx"
    assert canon.args == ["-y", "chrome-mcp"]
    assert canon.env == {"CHROME_KEY": "ck-FAKE"}

    claude_shape = from_canonical("claude", canon)
    assert claude_shape == {
        "command": "npx",
        "args": ["-y", "chrome-mcp"],
        "env": {"CHROME_KEY": "ck-FAKE"},
    }

    back = from_canonical("opencode", to_canonical("claude", claude_shape))
    assert back == {
        "type": "local",
        "command": ["npx", "-y", "chrome-mcp"],
        "environment": {"CHROME_KEY": "ck-FAKE"},
        "enabled": True,
    }


def test_canonical_remote_url_server(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    canon = to_canonical("claude", read_server_def("claude", "linear", home))
    assert canon.transport == "remote"
    assert canon.url == "https://mcp.linear.app/sse"
    opencode_shape = from_canonical("opencode", canon)
    assert opencode_shape == {
        "type": "remote",
        "url": "https://mcp.linear.app/sse",
        "enabled": True,
    }
    canon2 = to_canonical("opencode", read_server_def("opencode", "hermes", home))
    assert canon2.transport == "remote"
    assert from_canonical("cursor", canon2) == {"url": "http://localhost:8893/sse"}


def test_extras_not_carried_into_opencode_or_codex(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    canon = to_canonical("claude", read_server_def("claude", "github", home))
    assert "customField" not in from_canonical("opencode", canon)
    assert "customField" not in from_canonical("codex", canon)


def test_unsupported_shape_raises() -> None:
    with pytest.raises(ValueError):
        to_canonical("claude", {"note": "neither command nor url"})


def test_build_copy_patch_ops(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    target, ops, summary = build_copy_patch("claude", "gemini", "github", home)
    assert target.harness_id == "gemini"
    assert target.kind == "mcp_server"
    assert target.file_path == home / ".gemini" / "settings.json"
    assert target.file_format == "json"
    assert len(ops) == 1
    assert ops[0].op == "merge"
    assert ops[0].path == "mcpServers.github"
    assert ops[0].value["command"] == "gh-mcp"

    target2, ops2, _ = build_copy_patch("claude", "codex", "github", home)
    assert target2.file_format == "toml"
    assert ops2[0].path == "mcp_servers.github"

    target3, ops3, _ = build_copy_patch("claude", "opencode", "github", home)
    assert ops3[0].path == "mcp.github"
    assert ops3[0].value["type"] == "local"


def test_build_copy_patch_missing_source_raises(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    with pytest.raises(KeyError):
        build_copy_patch("claude", "gemini", "nonexistent", home)


def test_build_remove_patch_ops(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    target, ops, summary = build_remove_patch("claude", "github", home)
    assert target.harness_id == "claude"
    assert ops[0].op == "remove"
    assert ops[0].path == "mcpServers.github"
    assert summary["transport"] == "stdio"


def test_summarize_def_keys_only(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    summary = summarize_def(read_server_def("claude", "github", home))
    text = json.dumps(summary)
    assert "sk-FAKE-SECRET" not in text
    assert "gh-mcp" not in text  # command value is also withheld
    assert "GH_TOKEN" in text  # env key names are allowed
    assert summary["transport"] == "stdio"


def test_target_config_parse_error(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    assert target_config_parse_error("gemini", home) is None
    assert target_config_parse_error("qwen", home) is None
    missing_home = tmp_path / "empty"
    missing_home.mkdir()
    assert target_config_parse_error("gemini", missing_home) is None  # missing = creatable
    (home / ".gemini" / "settings.json").write_text("{broken", encoding="utf-8")
    error = target_config_parse_error("gemini", home)
    assert error is not None and "parse" in error.lower()


def test_summarize_def_claude_entry_with_type_field(tmp_path: Path) -> None:
    # Real ~/.claude.json entries can carry type:"stdio"; summarize must
    # not mistake them for opencode-shaped definitions.
    raw = {"type": "stdio", "command": "headroom-mcp", "args": ["--x"], "env": {"K": "v"}}
    summary = summarize_def(raw, tool="claude")
    assert summary["transport"] == "stdio"
    assert "command" in summary["fields"]
    assert "env:K" in summary["fields"]
