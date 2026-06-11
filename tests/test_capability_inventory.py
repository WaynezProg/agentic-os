"""Tests for the P40 capability inventory readers."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from agentic_os.capability_inventory import (
    read_all_capabilities,
    read_tool_capabilities,
)


def _make_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"

    # claude
    (home / ".claude" / "skills" / "browse").mkdir(parents=True)
    (home / ".claude" / "skills" / "tdd").mkdir(parents=True)
    (home / ".claude" / "plugins" / "cache" / "official").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("# memory\n", encoding="utf-8")
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {"command": "gh-mcp", "env": {"TOKEN": "sk-FAKE-SECRET"}},
                    "linear": {"url": "https://secret.example/sse"},
                }
            }
        ),
        encoding="utf-8",
    )

    # codex
    (home / ".codex" / "prompts").mkdir(parents=True)
    (home / ".codex" / "prompts" / "review.md").write_text("x", encoding="utf-8")
    (home / ".codex" / "config.toml").write_text(
        '[mcp_servers.context7]\ncommand = "npx-secret"\n\n[mcp_servers.semgrep]\ncommand = "y"\n',
        encoding="utf-8",
    )
    real_agents = home / ".config" / "agent-instructions.md"
    real_agents.parent.mkdir(parents=True, exist_ok=True)
    real_agents.write_text("# shared agents memory\n", encoding="utf-8")
    (home / ".codex" / "AGENTS.md").symlink_to(real_agents)

    # gemini
    (home / ".gemini" / "extensions" / "antigravity").mkdir(parents=True)
    (home / ".gemini" / "settings.json").write_text(
        json.dumps({"mcpServers": {"context7": {"command": "z"}}}), encoding="utf-8"
    )
    (home / ".gemini" / "GEMINI.md").write_text("gm\n", encoding="utf-8")

    # qwen
    (home / ".qwen" / "skills" / "gstack").mkdir(parents=True)
    (home / ".qwen" / "settings.json").write_text(
        json.dumps({"mcpServers": {"openclaw": {}}}), encoding="utf-8"
    )
    (home / ".qwen" / "QWEN.md").write_text("qw\n", encoding="utf-8")

    # opencode
    (home / ".config" / "opencode" / "skills" / "ship").mkdir(parents=True)
    (home / ".config" / "opencode" / "plugins").mkdir(parents=True)
    (home / ".config" / "opencode" / "plugins" / "notify.js").write_text(
        "x", encoding="utf-8"
    )
    (home / ".config" / "opencode" / "opencode.json").write_text(
        json.dumps({"mcp": {"hermes": {"type": "remote"}}}), encoding="utf-8"
    )
    (home / ".config" / "opencode" / "AGENTS.md").write_text("oc\n", encoding="utf-8")

    # cursor
    (home / ".cursor").mkdir(parents=True)
    (home / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"codegraph": {"command": "cg"}}}), encoding="utf-8"
    )

    return home


def test_claude_capabilities_basic(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    caps = read_tool_capabilities("claude", home)
    assert caps.present is True
    assert caps.skills == ["browse", "tdd"]
    assert caps.mcp_servers == ["github", "linear"]
    assert caps.plugins == ["official"]
    assert len(caps.memory_files) == 1
    memory = caps.memory_files[0]
    assert memory.path.endswith(".claude/CLAUDE.md")
    assert memory.size_bytes > 0
    assert memory.modified_at
    assert caps.error is None


def test_codex_toml_mcp_names(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    caps = read_tool_capabilities("codex", home)
    assert caps.mcp_servers == ["context7", "semgrep"]
    assert caps.skills == ["review"]


def test_codex_agents_md_symlink_stat(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    caps = read_tool_capabilities("codex", home)
    assert len(caps.memory_files) == 1
    assert caps.memory_files[0].path.endswith(".codex/AGENTS.md")
    assert caps.memory_files[0].size_bytes > 0


def test_gemini_qwen_opencode_cursor(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    gemini = read_tool_capabilities("gemini", home)
    assert gemini.mcp_servers == ["context7"]
    assert gemini.plugins == ["antigravity"]
    qwen = read_tool_capabilities("qwen", home)
    assert qwen.skills == ["gstack"]
    assert qwen.mcp_servers == ["openclaw"]
    opencode = read_tool_capabilities("opencode", home)
    assert opencode.skills == ["ship"]
    assert opencode.plugins == ["notify.js"]
    assert opencode.mcp_servers == ["hermes"]
    cursor = read_tool_capabilities("cursor", home)
    assert cursor.mcp_servers == ["codegraph"]
    assert cursor.memory_files == []


def test_missing_tool_reports_present_false(tmp_path: Path) -> None:
    home = tmp_path / "empty-home"
    home.mkdir()
    caps = read_tool_capabilities("claude", home)
    assert caps.present is False
    assert caps.skills == []
    assert caps.error is None


def test_bad_json_reports_error_not_crash(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    (home / ".claude.json").write_text("{broken", encoding="utf-8")
    caps = read_tool_capabilities("claude", home)
    assert caps.present is True
    assert caps.mcp_servers == []
    assert caps.error is not None


def test_secret_values_never_in_output(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    payload = json.dumps([asdict(c) for c in read_all_capabilities(home)])
    assert "sk-FAKE-SECRET" not in payload
    assert "npx-secret" not in payload
    assert "secret.example" not in payload


def test_oversized_config_skipped(tmp_path: Path, monkeypatch) -> None:
    import agentic_os.capability_inventory as ci

    home = _make_home(tmp_path)
    monkeypatch.setattr(ci, "_MAX_CONFIG_BYTES", 10)
    caps = read_tool_capabilities("claude", home)
    assert caps.mcp_servers == []
    assert caps.error is not None and "large" in caps.error


def test_read_all_capabilities_order(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    tools = [c.tool for c in read_all_capabilities(home)]
    assert tools == ["claude", "codex", "gemini", "qwen", "opencode", "cursor"]
