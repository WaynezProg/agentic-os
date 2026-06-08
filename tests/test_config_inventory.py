"""Tests for config inventory (P34)."""
import json
import tempfile
from pathlib import Path

from agentic_os.config_inventory import (
    ConfigSummary,
    read_config_summary,
    _read_claude_config,
    _read_codex_config,
    _read_generic_json_config,
)


def test_config_summary_model():
    """ConfigSummary should hold non-secret config fields."""
    summary = ConfigSummary(
        config_source="/home/user/.claude/settings.json",
        model="claude-sonnet-4-20250514",
        provider="anthropic",
        system_prompt_path=None,
        parse_error=None,
    )
    assert summary.model == "claude-sonnet-4-20250514"
    assert summary.parse_error is None


def test_read_config_summary_missing_path():
    """Should return error for non-existent config path."""
    summary = read_config_summary("claude", "/nonexistent/path/xyz")
    assert summary.config_source == "/nonexistent/path/xyz"
    assert summary.parse_error is not None
    assert "not found" in summary.parse_error or "does not exist" in summary.parse_error


def test_read_claude_config_json():
    """Should parse Claude settings.json for model."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = Path(tmpdir) / "settings.json"
        settings.write_text(json.dumps({
            "model": "claude-sonnet-4-20250514",
            "provider": "anthropic",
        }))
        summary = _read_claude_config(tmpdir)
        assert summary.model == "claude-sonnet-4-20250514"
        assert summary.provider == "anthropic"
        assert summary.parse_error is None


def test_read_claude_config_missing():
    """Should handle missing Claude config dir."""
    summary = _read_claude_config("/nonexistent/claude/dir")
    assert summary.parse_error is not None


def test_read_codex_config_toml():
    """Should parse Codex config.toml for model."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Path(tmpdir) / "config.toml"
        config.write_text('[defaults]\nmodel = "o4-mini"\n')
        summary = _read_codex_config(tmpdir)
        assert summary.model == "o4-mini"
        assert summary.parse_error is None


def test_read_generic_json_config():
    """Should parse generic JSON config for model field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Path(tmpdir) / "config.json"
        config.write_text(json.dumps({"model": "gpt-4", "provider": "openai"}))
        summary = _read_generic_json_config(tmpdir, "config.json")
        assert summary.model == "gpt-4"
        assert summary.provider == "openai"


def test_no_secrets_leaked():
    """Config readers should never return API keys or tokens."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = Path(tmpdir) / "settings.json"
        settings.write_text(json.dumps({
            "model": "claude-sonnet-4-20250514",
            "api_key": "sk-secret-key-12345",
            "token": "bearer-token-xyz",
        }))
        summary = _read_claude_config(tmpdir)
        # api_key and token should NOT appear in summary
        assert summary.model == "claude-sonnet-4-20250514"
        # Verify no secret fields in the dataclass
        assert not hasattr(summary, "api_key")
        assert not hasattr(summary, "token")


def test_read_config_summary_dispatch():
    """read_config_summary should dispatch to correct reader by agent_id."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a Claude-style config
        settings = Path(tmpdir) / "settings.json"
        settings.write_text(json.dumps({"model": "claude-sonnet-4-20250514"}))

        summary = read_config_summary("claude", tmpdir)
        assert summary.model == "claude-sonnet-4-20250514"
