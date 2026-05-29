from __future__ import annotations

from pathlib import Path

from agentic_os.control_plane import (
    ControlPlaneStore,
    McpServerUpsert,
    PolicyEvaluationRequest,
    PolicyUpsert,
    SkillUpsert,
)


def make_store(tmp_path: Path) -> ControlPlaneStore:
    store = ControlPlaneStore(tmp_path / "agentic-os.db")
    store.init()
    return store


def test_skill_registry_upserts_lists_shows_and_disables_records(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    created = store.upsert_skill(
        "reviewer",
        SkillUpsert(
            label="Reviewer",
            description="Review local changes",
            source="workspace",
            entrypoint="skills/reviewer/SKILL.md",
            tags=["review", "local"],
        ),
    )
    listed = store.list_skills()
    shown = store.get_skill("reviewer")
    disabled = store.disable_skill("reviewer")

    assert created.id == "reviewer"
    assert created.enabled is True
    assert [skill.id for skill in listed] == ["reviewer"]
    assert shown.label == "Reviewer"
    assert shown.tags == ["review", "local"]
    assert disabled.enabled is False
    assert store.get_skill("reviewer").enabled is False


def test_mcp_registry_redacts_preview_and_stores_env_keys_only(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    created = store.upsert_mcp_server(
        "figma",
        McpServerUpsert(
            label="Figma MCP",
            description="Local MCP metadata",
            transport="http",
            command_preview=[
                "figma-mcp",
                "--token",
                "TOKEN_PLACEHOLDER",
                "--password=TOKEN_PLACEHOLDER",
                "--safe-flag",
            ],
            url="https://user:TOKEN_PLACEHOLDER@example.invalid/mcp",
            env_keys=["FIGMA_TOKEN"],
        ),
    )
    disabled = store.disable_mcp_server("figma")

    stored_text = " ".join(created.command_preview) + " " + str(created.url)
    assert "TOKEN_PLACEHOLDER" not in stored_text
    assert "[REDACTED]" in stored_text
    assert created.env_keys == ["FIGMA_TOKEN"]
    assert created.enabled is True
    assert disabled.enabled is False


def test_mcp_registry_strips_env_values_before_storage(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    created = store.upsert_mcp_server(
        "figma",
        McpServerUpsert(
            label="Figma MCP",
            env_keys=["FIGMA_TOKEN=TOKEN_PLACEHOLDER", "SAFE_ENV"],
        ),
    )

    assert created.env_keys == ["FIGMA_TOKEN", "SAFE_ENV"]
    assert "TOKEN_PLACEHOLDER" not in " ".join(created.env_keys)


def test_mcp_registry_redacts_realistic_secret_values(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    created = store.upsert_mcp_server(
        "secrets",
        McpServerUpsert(
            label="Secret-shaped MCP",
            command_preview=[
                "mcp-server",
                "--password=secret123",
                "--api-key=sk-live-abc",
            ],
            url="https://example.invalid/mcp?token=secret123&safe=true",
        ),
    )

    stored_text = " ".join(created.command_preview) + " " + str(created.url)
    assert "secret123" not in stored_text
    assert "sk-live-abc" not in stored_text
    assert "token=[REDACTED]" in stored_text
    assert "password=[REDACTED]" in stored_text
    assert "api-key=[REDACTED]" in stored_text


def test_mcp_registry_redacts_whitespace_flags_and_authorization_headers(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    created = store.upsert_mcp_server(
        "headers",
        McpServerUpsert(
            label="Header-shaped MCP",
            command_preview=[
                "mcp-server --password secret123 --safe",
                "--header",
                "Authorization: Bearer bearer-secret-123",
            ],
        ),
    )

    stored_text = " ".join(created.command_preview)
    assert "secret123" not in stored_text
    assert "bearer-secret-123" not in stored_text
    assert "--password [REDACTED]" in stored_text
    assert "Authorization: Bearer [REDACTED]" in stored_text


def test_policy_evaluation_denies_missing_or_disabled_policy(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_skill("reviewer", SkillUpsert(label="Reviewer"))

    missing = store.evaluate_policy(
        PolicyEvaluationRequest(agent_id="agent-a", skill_id="reviewer")
    )
    store.upsert_policy("agent-a", PolicyUpsert(enabled=False, allowed_skill_ids=["reviewer"]))
    disabled = store.evaluate_policy(
        PolicyEvaluationRequest(agent_id="agent-a", skill_id="reviewer")
    )

    assert missing.decision == "deny"
    assert missing.reason == "no policy configured for agent-a"
    assert disabled.decision == "deny"
    assert disabled.reason == "policy disabled for agent-a"


def test_policy_evaluation_allows_matching_enabled_registry_and_policy(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_skill("reviewer", SkillUpsert(label="Reviewer"))
    store.upsert_mcp_server("filesystem", McpServerUpsert(label="Filesystem MCP"))
    store.upsert_policy(
        "agent-a",
        PolicyUpsert(
            allowed_skill_ids=["reviewer"],
            allowed_mcp_server_ids=["filesystem"],
            allowed_tool_names=["read"],
            allowed_model_ids=["local-model"],
            cwd_roots=[str(tmp_path)],
            rate_limit_per_minute=10,
        ),
    )

    result = store.evaluate_policy(
        PolicyEvaluationRequest(
            agent_id="agent-a",
            skill_id="reviewer",
            mcp_server_id="filesystem",
            tool_name="read",
            model_id="local-model",
            cwd=str(tmp_path / "project"),
        )
    )

    assert result.decision == "allow"
    assert result.reason == "policy allowed request"


def test_policy_evaluation_denies_unknown_or_disabled_registry_records(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_skill("disabled-skill", SkillUpsert(label="Disabled Skill"))
    store.disable_skill("disabled-skill")
    store.upsert_mcp_server("disabled-mcp", McpServerUpsert(label="Disabled MCP"))
    store.disable_mcp_server("disabled-mcp")
    store.upsert_policy(
        "agent-a",
        PolicyUpsert(
            allowed_skill_ids=["*"],
            allowed_mcp_server_ids=["*"],
            rate_limit_per_minute=10,
        ),
    )

    unknown_skill = store.evaluate_policy(
        PolicyEvaluationRequest(agent_id="agent-a", skill_id="missing")
    )
    disabled_skill = store.evaluate_policy(
        PolicyEvaluationRequest(agent_id="agent-a", skill_id="disabled-skill")
    )
    disabled_mcp = store.evaluate_policy(
        PolicyEvaluationRequest(agent_id="agent-a", mcp_server_id="disabled-mcp")
    )

    assert unknown_skill.decision == "deny"
    assert unknown_skill.reason == "unknown skill missing"
    assert disabled_skill.decision == "deny"
    assert disabled_skill.reason == "skill disabled-skill is disabled"
    assert disabled_mcp.decision == "deny"
    assert disabled_mcp.reason == "mcp server disabled-mcp is disabled"


def test_policy_evaluation_denies_allowlist_scope_readonly_and_rate_limit_violations(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.upsert_skill("reviewer", SkillUpsert(label="Reviewer"))
    store.upsert_policy(
        "agent-a",
        PolicyUpsert(
            readonly=True,
            allowed_skill_ids=["other"],
            allowed_tool_names=["read", "write"],
            allowed_model_ids=["allowed-model"],
            cwd_roots=[str(tmp_path / "allowed")],
            rate_limit_per_minute=0,
        ),
    )

    denied_skill = store.evaluate_policy(
        PolicyEvaluationRequest(agent_id="agent-a", skill_id="reviewer")
    )
    denied_model = store.evaluate_policy(
        PolicyEvaluationRequest(agent_id="agent-a", model_id="blocked-model")
    )
    denied_cwd = store.evaluate_policy(
        PolicyEvaluationRequest(agent_id="agent-a", cwd=str(tmp_path / "blocked"))
    )
    denied_readonly = store.evaluate_policy(
        PolicyEvaluationRequest(agent_id="agent-a", tool_name="write")
    )
    denied_rate_limit = store.evaluate_policy(PolicyEvaluationRequest(agent_id="agent-a"))

    assert denied_skill.reason == "skill reviewer is not allowed for agent-a"
    assert denied_model.reason == "model blocked-model is not allowed for agent-a"
    assert denied_cwd.reason == "cwd is outside allowed roots for agent-a"
    assert denied_readonly.reason == "readonly policy denies write"
    assert denied_rate_limit.reason == "rate_limit_per_minute must be at least 1"
    assert {result.decision for result in [denied_skill, denied_model, denied_cwd]} == {"deny"}


def test_policy_evaluation_allowlist_mismatch_takes_precedence_over_scope_and_readonly(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.upsert_policy(
        "agent-a",
        PolicyUpsert(
            readonly=True,
            allowed_tool_names=["read"],
            cwd_roots=[str(tmp_path / "allowed")],
            rate_limit_per_minute=10,
        ),
    )

    result = store.evaluate_policy(
        PolicyEvaluationRequest(
            agent_id="agent-a",
            tool_name="write",
            cwd=str(tmp_path / "blocked"),
        )
    )

    assert result.decision == "deny"
    assert result.reason == "tool write is not allowed for agent-a"


def test_policy_evaluation_returns_approval_required_for_matching_tool(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_policy(
        "agent-a",
        PolicyUpsert(
            allowed_tool_names=["exec"],
            approval_required_tool_names=["exec"],
            rate_limit_per_minute=10,
        ),
    )

    result = store.evaluate_policy(PolicyEvaluationRequest(agent_id="agent-a", tool_name="exec"))

    assert result.decision == "approval_required"
    assert result.reason == "tool exec requires approval"


def test_policy_evaluation_invalid_rate_limit_takes_precedence_over_approval(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    store.upsert_policy(
        "agent-a",
        PolicyUpsert(
            allowed_tool_names=["exec"],
            approval_required_tool_names=["exec"],
            rate_limit_per_minute=0,
        ),
    )

    result = store.evaluate_policy(PolicyEvaluationRequest(agent_id="agent-a", tool_name="exec"))

    assert result.decision == "deny"
    assert result.reason == "rate_limit_per_minute must be at least 1"


def test_policy_evaluation_is_deterministic_for_same_input(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_policy(
        "agent-a",
        PolicyUpsert(
            allowed_tool_names=["read"],
            allowed_model_ids=["local-model"],
            rate_limit_per_minute=10,
        ),
    )
    request = PolicyEvaluationRequest(
        agent_id="agent-a",
        tool_name="read",
        model_id="local-model",
    )

    first = store.evaluate_policy(request)
    second = store.evaluate_policy(request)

    assert first == second


def test_skill_can_be_deprecated_and_upsert_resets_deprecated(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_skill("reviewer", SkillUpsert(label="Reviewer"))

    result = store.deprecate_skill("reviewer")
    assert result.deprecated is True

    # upsert resets deprecated
    store.upsert_skill("reviewer", SkillUpsert(label="Reviewer v2"))
    result = store.get_skill("reviewer")
    assert result.deprecated is False


def test_mcp_server_can_be_deprecated_and_upsert_resets_deprecated(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_mcp_server("filesystem", McpServerUpsert(label="FS"))

    result = store.deprecate_mcp_server("filesystem")
    assert result.deprecated is True

    store.upsert_mcp_server("filesystem", McpServerUpsert(label="FS v2"))
    result = store.get_mcp_server("filesystem")
    assert result.deprecated is False


def test_policy_can_be_deprecated_and_upsert_resets_deprecated(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_policy("shell", PolicyUpsert())

    result = store.deprecate_policy("shell")
    assert result.deprecated is True

    store.upsert_policy("shell", PolicyUpsert())
    result = store.get_policy("shell")
    assert result.deprecated is False


def test_policy_evaluation_warns_for_deprecated_policy_skill_and_mcp(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_skill("reviewer", SkillUpsert(label="Reviewer"))
    store.upsert_mcp_server("filesystem", McpServerUpsert(label="FS"))
    store.upsert_policy(
        "shell",
        PolicyUpsert(
            allowed_skill_ids=["reviewer"],
            allowed_mcp_server_ids=["filesystem"],
            allowed_tool_names=["*"],
            allowed_model_ids=["*"],
            cwd_roots=["/tmp"],
        ),
    )

    # Deprecate all three
    store.deprecate_skill("reviewer")
    store.deprecate_mcp_server("filesystem")
    store.deprecate_policy("shell")

    result = store.evaluate_policy(
        PolicyEvaluationRequest(
            agent_id="shell",
            skill_id="reviewer",
            mcp_server_id="filesystem",
            cwd="/tmp",
        )
    )

    # Decision is still allow — deprecated != denied
    assert result.decision == "allow"
    assert len(result.warnings) == 3
    assert any("policy" in w and "deprecated" in w for w in result.warnings)
    assert any("skill" in w and "deprecated" in w for w in result.warnings)
    assert any("mcp" in w and "deprecated" in w for w in result.warnings)


def test_policy_evaluation_no_warnings_when_not_deprecated(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_skill("reviewer", SkillUpsert(label="Reviewer"))
    store.upsert_policy(
        "shell",
        PolicyUpsert(
            allowed_skill_ids=["reviewer"],
            allowed_tool_names=["*"],
            allowed_model_ids=["*"],
            cwd_roots=["/tmp"],
        ),
    )

    result = store.evaluate_policy(
        PolicyEvaluationRequest(
            agent_id="shell",
            skill_id="reviewer",
            cwd="/tmp",
        )
    )
    assert result.decision == "allow"
    assert result.warnings == []
