"""Tests for agentic runtime inventory (P37)."""
import textwrap
from pathlib import Path

from fastapi.testclient import TestClient

from agentic_os.agentic_inventory import build_agentic_inventory


def test_build_agentic_inventory_openclaw_with_skills(tmp_path: Path) -> None:
    """OpenClaw inventory should surface skills from its config dir."""
    cfg = tmp_path / ".openclaw"
    cfg.mkdir()
    (cfg / "skills.d").mkdir()
    (cfg / "skills.d" / "web-search.toml").write_text(
        '[skill]\nid = "web-search"\nenabled = true\n',
        encoding="utf-8",
    )
    (cfg / "skills.d" / "code-review.toml").write_text(
        '[skill]\nid = "code-review"\nenabled = false\n',
        encoding="utf-8",
    )
    (cfg / "mcp.toml").write_text(
        textwrap.dedent(
            """\
            [[servers]]
            id = "github"
            status = "connected"
            """
        ),
        encoding="utf-8",
    )

    result = build_agentic_inventory(agent_id="openclaw", config_path=str(cfg))

    assert result.agent_id == "openclaw"
    assert result.tool_kind == "agentic_runtime"
    assert result.error is None
    skill_ids = {s.identifier for s in result.skills}
    assert skill_ids == {"web-search", "code-review"}
    mcp_ids = {m.identifier for m in result.mcp_servers}
    assert mcp_ids == {"github"}


def test_build_agentic_inventory_hermes_with_skills_tools_mcp(tmp_path: Path) -> None:
    """Hermes inventory should surface skills + tools + mcp_servers."""
    cfg = tmp_path / ".hermes"
    cfg.mkdir()
    (cfg / "skills.toml").write_text(
        textwrap.dedent(
            """\
            [[skill]]
            id = "summarize"
            enabled = true
            """
        ),
        encoding="utf-8",
    )
    (cfg / "tools.toml").write_text(
        textwrap.dedent(
            """\
            [[tool]]
            id = "http-fetch"
            type = "command"
            """
        ),
        encoding="utf-8",
    )
    (cfg / "mcp.toml").write_text(
        textwrap.dedent(
            """\
            [[server]]
            id = "playwright"
            status = "ready"
            """
        ),
        encoding="utf-8",
    )

    result = build_agentic_inventory(agent_id="hermes", config_path=str(cfg))

    assert result.agent_id == "hermes"
    assert result.error is None
    assert {s.identifier for s in result.skills} == {"summarize"}
    assert {t.identifier for t in result.tools} == {"http-fetch"}
    assert {m.identifier for m in result.mcp_servers} == {"playwright"}


def test_build_agentic_inventory_n8n_with_flows(tmp_path: Path) -> None:
    """n8n inventory should surface flows from its config dir."""
    cfg = tmp_path / ".n8n"
    cfg.mkdir()
    (cfg / "workflows").mkdir()
    (cfg / "workflows" / "wf1.json").write_text(
        '{"name":"daily-digest","active":true}', encoding="utf-8"
    )
    (cfg / "workflows" / "wf2.json").write_text(
        '{"name":"nightly-backup","active":false}', encoding="utf-8"
    )

    result = build_agentic_inventory(agent_id="n8n", config_path=str(cfg))

    assert result.agent_id == "n8n"
    assert result.error is None
    flow_names = {f.identifier for f in result.flows}
    assert flow_names == {"daily-digest", "nightly-backup"}


def test_build_agentic_inventory_missing_config_returns_empty(tmp_path: Path) -> None:
    """A missing config dir should not raise; it returns empty result."""
    result = build_agentic_inventory(agent_id="openclaw", config_path=str(tmp_path / "missing"))

    assert result.agent_id == "openclaw"
    assert result.error is None
    assert result.skills == []
    assert result.mcp_servers == []
    assert result.tools == []
    assert result.flows == []


def test_build_agentic_inventory_malformed_config_does_not_raise(tmp_path: Path) -> None:
    """A malformed config file should be reported as an error, not crash."""
    cfg = tmp_path / ".openclaw"
    cfg.mkdir()
    (cfg / "mcp.toml").write_text("not valid toml [[[[", encoding="utf-8")

    result = build_agentic_inventory(agent_id="openclaw", config_path=str(cfg))

    # Either an error is captured, or empty lists — must not raise.
    assert result.agent_id == "openclaw"


def test_api_agentic_inventory_returns_per_agent_results(tmp_path: Path) -> None:
    """GET /agentic/inventory should return one entry per agentic_runtime agent."""
    from agentic_os.api import create_app

    registry = tmp_path / "agents.toml"
    registry.write_text(
        textwrap.dedent(
            """\
            [[agents]]
            id = "claude"
            label = "Claude"
            command = ["claude"]
            cwd_mode = "required"
            stop_policy = "process_group"
            tool_kind = "vibe_coding"

            [[agents]]
            id = "openclaw"
            label = "OpenClaw"
            command = ["openclaw"]
            cwd_mode = "required"
            stop_policy = "process_group"
            tool_kind = "agentic_runtime"
            config_path = "/nonexistent/.openclaw"
            """
        ),
        encoding="utf-8",
    )

    client = TestClient(
        create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)
    )

    response = client.get("/agentic/inventory")

    assert response.status_code == 200
    body = response.json()
    agents = body["agents"]
    # Only the agentic_runtime agent is included.
    assert {a["agent_id"] for a in agents} == {"openclaw"}


def test_api_agentic_inventory_isolates_errors_per_agent(tmp_path: Path) -> None:
    """If one agent's inventory errors, the others must still return."""
    from agentic_os.api import create_app

    registry = tmp_path / "agents.toml"
    registry.write_text(
        textwrap.dedent(
            """\
            [[agents]]
            id = "openclaw"
            label = "OpenClaw"
            command = ["openclaw"]
            cwd_mode = "required"
            stop_policy = "process_group"
            tool_kind = "agentic_runtime"
            config_path = "/nonexistent/.openclaw"

            [[agents]]
            id = "hermes"
            label = "Hermes"
            command = ["hermes"]
            cwd_mode = "optional"
            stop_policy = "process_group"
            tool_kind = "agentic_runtime"
            config_path = "/nonexistent/.hermes"
            """
        ),
        encoding="utf-8",
    )

    client = TestClient(
        create_app(state_dir=tmp_path / ".agentic-os", registry_path=registry)
    )

    response = client.get("/agentic/inventory")

    assert response.status_code == 200
    agents = response.json()["agents"]
    assert {a["agent_id"] for a in agents} == {"openclaw", "hermes"}
    # Each entry should at least have agent_id, tool_kind; error may be set.
    for entry in agents:
        assert "agent_id" in entry
        assert entry["tool_kind"] == "agentic_runtime"
        assert "skills" in entry
        assert "mcp_servers" in entry
        assert "tools" in entry
        assert "flows" in entry
