from __future__ import annotations

from agentic_os.schema_registry import SchemaRegistry


def test_validate_claude_mcp_document_ok() -> None:
    reg = SchemaRegistry()
    doc = {"mcpServers": {"gh": {"command": "npx", "args": ["-y", "mcp"]}}, "model": "x"}
    errors = reg.validate_document("claude", "mcp_server", doc)
    assert errors == []


def test_validate_claude_mcp_document_rejects_bad_type() -> None:
    reg = SchemaRegistry()
    doc = {"mcpServers": {"gh": {"command": 123}}}
    errors = reg.validate_document("claude", "mcp_server", doc)
    assert errors


def test_path_whitelist_allows_mcp_servers() -> None:
    reg = SchemaRegistry()
    assert reg.is_path_allowed("claude", "mcp_server", "mcpServers.github") is True
    assert reg.is_path_allowed("claude", "mcp_server", "permissions.allow") is False


def test_validate_registry_allows_model_arg_and_provider_env() -> None:
    reg = SchemaRegistry()
    doc = {
        "agents": [
            {
                "id": "shell",
                "label": "Shell",
                "command": ["/usr/bin/printf", "{{message}}"],
                "model_arg": ["--model", "{{model}}"],
                "provider_env": "TEST_PROVIDER",
            }
        ]
    }
    assert reg.validate_document("agentic_os", "registry", doc) == []
