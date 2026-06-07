from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "apps" / "web"
INDEX_HTML = WEB_DIR / "index.html"
STYLES_CSS = WEB_DIR / "styles.css"
APP_JS = WEB_DIR / "app.js"
API_JS = WEB_DIR / "api.js"
CATALOG_EDITOR_JS = WEB_DIR / "ui" / "catalog-editor.js"
CONFIG_EDITOR_JS = WEB_DIR / "ui" / "config-editor.js"
PROFILE_EDITOR_JS = WEB_DIR / "ui" / "profile-editor.js"
REGISTRY_EDITOR_JS = WEB_DIR / "ui" / "registry-editor.js"
CONTROL_PLANE_EDITOR_JS = WEB_DIR / "ui" / "control-plane-editor.js"
ROLLBACK_JS = WEB_DIR / "ui" / "rollback.js"
ACTIONS_JS = WEB_DIR / "ui" / "actions.js"


def _web_javascript_sources() -> str:
    return "".join(
        path.read_text(encoding="utf-8")
        for path in (
            APP_JS,
            API_JS,
            CATALOG_EDITOR_JS,
            CONFIG_EDITOR_JS,
            PROFILE_EDITOR_JS,
            REGISTRY_EDITOR_JS,
            CONTROL_PLANE_EDITOR_JS,
            ROLLBACK_JS,
            ACTIONS_JS,
        )
        if path.is_file()
    )


def test_static_web_files_exist() -> None:
    assert INDEX_HTML.is_file()
    assert STYLES_CSS.is_file()
    assert APP_JS.is_file()
    assert (WEB_DIR / "i18n.js").is_file()


def test_five_tabs_are_present() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert html.count('role="tab"') == 11
    for tab in [
        "代理",
        "執行",
        "日誌",
        "記憶",
        "技能 / MCP",
        "機群",
        "Harness",
        "介面",
        "核准",
        "稽核",
        "總覽",
    ]:
        assert re.search(rf">\s*{re.escape(tab)}\s*<", html)


def test_daemon_api_override_input_exists() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="api-url"' in html
    assert 'value="http://127.0.0.1:8767"' in html


def test_first_screen_is_control_panel_not_marketing_page() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8").lower()

    assert '<main class="workspace">' in html
    assert 'id="panel-agents"' in html
    assert 'class="panel is-active"' in html
    assert 'id="api-status"' in html
    assert 'id="refresh-all"' in html
    for forbidden in ["hero", "landing", "get started", "sign up", "pricing"]:
        assert forbidden not in html


def test_agents_table_contract_exists() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    assert 'id="agents-table"' in html
    assert 'id="agents-body"' in html
    assert 'id="run-command-preview"' in html
    assert "updateRunCommandPreview" in js
    assert "formatArgv" in js
    for header in ["ID", "名稱", "啟用", "工作目錄模式", "停止策略", "啟動範本"]:
        assert re.search(rf"<th>\s*{re.escape(header)}\s*</th>", html)


def test_approvals_tab_uses_distinct_body_and_session_links() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    assert 'byId("approvals-embed-body")' in js
    assert 'byId("approvals-tab-body")' in js
    assert "renderApprovalTabRow" in js
    assert 'data-action="select-session"' in js


def test_session_timeline_panel_exists() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    assert 'id="session-timeline"' in html
    assert "loadSessionTimeline" in js


def test_sessions_actions_contract_exists() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    assert 'id="sessions-table"' in html
    assert 'id="sessions-body"' in html
    for action in ["logs", "summarize", "review-create", "retry", "stop"]:
        assert f'data-action="{action}"' in js


def test_logs_controls_contract_exists() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="log-session-id"' in html
    assert 'id="log-stream"' in html
    assert '<option value="">merged</option>' in html
    assert '<option value="stdout">stdout</option>' in html
    assert '<option value="stderr">stderr</option>' in html
    assert 'id="log-after"' in html
    assert 'id="log-output"' in html


def test_memory_controls_contract_exists() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    assert 'id="memory-review-table"' in html
    assert 'id="memory-review-body"' in html
    assert 'id="memories-table"' in html
    assert 'id="memories-body"' in html
    assert 'id="memory-search"' in html
    assert 'id="memory-summary-output"' in html
    assert 'data-action="approve-memory"' in js
    assert 'data-action="reject-memory"' in js
    assert 'data-action="view-summary"' in js


def test_memory_copy_identifies_summary_review_pointers() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "證據摘要" in html
    assert "review pointer" in html


def test_readme_positions_session2memory_as_formal_memory_owner() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "session2memory owns formal memory compilation" in readme
    assert "agentic-os owns harness-run evidence" in readme


def test_skills_mcp_placeholder_panels_exist() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="panel-skills"' in html
    assert 'id="skills-table"' in html
    assert 'id="skills-body"' in html
    assert 'id="mcp-table"' in html
    assert 'id="mcp-body"' in html
    assert 'id="approvals-table"' in html
    assert 'id="approvals-embed-body"' in html
    assert 'id="approvals-tab-body"' in html
    assert html.count('id="approvals-body"') == 0


def test_skills_mcp_p3_registry_tables_exist() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    for header in ["ID", "名稱", "啟用", "來源", "標籤"]:
        assert re.search(rf"<th>\s*{re.escape(header)}\s*</th>", html)
    for header in ["ID", "名稱", "啟用", "傳輸", "指令預覽"]:
        assert re.search(rf"<th>\s*{re.escape(header)}\s*</th>", html)


def test_policy_summary_and_evaluation_controls_exist() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="policy-summary-body"' in html
    assert 'id="policy-eval-agent"' in html
    assert 'id="policy-eval-skill"' in html
    assert 'id="policy-eval-mcp"' in html
    assert 'id="policy-eval-tool"' in html
    assert 'id="policy-eval-model"' in html
    assert 'id="policy-eval-cwd"' in html
    assert 'id="run-policy-eval"' in html
    assert 'id="policy-eval-result"' in html


def test_javascript_references_required_daemon_endpoints() -> None:
    js = _web_javascript_sources()

    for endpoint in [
        "/health",
        "/agents",
        "/sessions",
        "/sessions/{session_id}",
        "/sessions/{session_id}/logs",
        "/sessions/{session_id}/stop",
        "/sessions/{session_id}/retry",
        "/sessions/{session_id}/memory/summary",
        "/sessions/{session_id}/memory/review",
        "/memory/review",
        "/memory/review/{item_id}/approve",
        "/memory/review/{item_id}/reject",
        "/memory",
        "/memory/search",
        "/skills",
        "/mcp",
        "/policy",
        "/policy/evaluate",
        "/approvals",
        "/approvals/{approval_id}/approve",
        "/approvals/{approval_id}/reject",
        "/fleet/health",
        "/fleet/events",
        "/fleet/capacity",
        "/fleet/probe",
    ]:
        assert endpoint in js


def test_javascript_renders_policy_summary_and_evaluation_result() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    assert "loadPolicies" in js
    assert "evaluatePolicy" in js
    assert "policySummary" in js
    assert "policyEvaluate" in js
    assert "policy-eval-result" in js


def test_javascript_uses_session_detail_and_summary_read_paths() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    assert "sessionDetail" in js
    assert "loadSessionDetail" in js
    assert "renderSessionDetail" in js
    assert "loadSessionSummary" in js
    assert "renderSessionSummary" in js
    assert 'method: "GET"' in js


def test_javascript_does_not_spawn_processes() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    forbidden = [
        "child_process",
        "subprocess",
        "exec(",
        "spawn(",
        "fork(",
        "osascript",
        "readFile",
        "writeFile",
    ]
    for token in forbidden:
        assert token not in js


def test_log_rendering_is_bounded() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    assert re.search(r"const\s+MAX_LOG_ENTRIES\s*=\s*\d+", js)
    assert "trimLogEntries" in js
    assert ".slice(-MAX_LOG_ENTRIES)" in js


def test_session_logs_action_loads_logs_once_while_manual_refresh_still_works() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    match = re.search(
        r'\(action === "logs" \|\| action === "select-session"\) && sessionId\) \{(?P<body>.*?)\n    \} else if',
        js,
        re.DOTALL,
    )
    assert match is not None
    logs_action_body = match.group("body")

    assert 'byId("load-logs").addEventListener("click", loadLogs)' in js
    assert "function selectSession(sessionId)" in js
    assert "await selectSession(sessionId);" in logs_action_body
    assert logs_action_body.count("selectSession(") == 1
    assert "loadSessionTimeline" in js


def test_no_node_build_or_package_requirement_is_introduced() -> None:
    for path in [
        WEB_DIR / "package.json",
        WEB_DIR / "package-lock.json",
        WEB_DIR / "pnpm-lock.yaml",
        WEB_DIR / "yarn.lock",
        WEB_DIR / "node_modules",
    ]:
        assert not path.exists()

    combined = (
        INDEX_HTML.read_text(encoding="utf-8")
        + _web_javascript_sources()
        + (WEB_DIR / "i18n.js").read_text(encoding="utf-8")
    )
    for token in ["vite", "webpack", "parcel", "npm install", "node_modules"]:
        assert token not in combined.lower()


def test_catalog_harness_select_has_seven_options() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    for harness_id in ("claude", "codex", "opencode", "qwen", "openclaw", "hermes", "cursor"):
        assert f'<option value="{harness_id}">' in html


def test_harness_native_config_panel_exists() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = _web_javascript_sources()
    assert 'id="harness-config-snippet"' in html
    assert "loadHarnessNativeConfig" in js
    assert "/harness-config/{harness_id}/effective" in js


def test_javascript_does_not_pass_endpoint_keys_directly_to_api_fetch() -> None:
    js = _web_javascript_sources()

    assert re.search(r'apiFetch\("[A-Za-z][A-Za-z0-9]*"', js) is None


def test_fleet_tab_and_panel_exist() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'data-tab="fleet"' in html
    assert 'id="panel-fleet"' in html
    assert 'id="fleet-health-table"' in html
    assert 'id="fleet-health-body"' in html
    assert 'id="fleet-events-table"' in html
    assert 'id="fleet-events-body"' in html
    assert 'id="fleet-capacity-display"' in html
    assert 'id="fleet-probe-btn"' in html


def test_fleet_javascript_references_fleet_endpoints() -> None:
    js = _web_javascript_sources()
    for endpoint in [
        "/fleet/health",
        "/fleet/{agent_id}/health",
        "/fleet/events",
        "/fleet/capacity",
        "/fleet/probe",
    ]:
        assert endpoint in js


def test_fleet_javascript_has_required_functions() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    for fn in [
        "loadFleet",
        "loadFleetHealth",
        "loadFleetCapacity",
        "loadFleetEvents",
        "triggerFleetProbe",
        "healthPillClass",
    ]:
        assert fn in js


def test_fleet_tab_has_audit_events_section() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="audit-events-table"' in html
    assert 'id="audit-events-body"' in html
    assert 'id="audit-domain"' in html
    assert 'id="load-audit-events"' in html


def test_javascript_references_audit_endpoints() -> None:
    js = _web_javascript_sources()
    for endpoint in [
        "/audit/events",
        "/audit/policy-coverage",
    ]:
        assert endpoint in js


def test_javascript_has_load_audit_events_function() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    assert "loadAuditEvents" in js


def test_javascript_renders_deprecated_badges() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    assert "is-deprecated" in js
    assert ".deprecated" in js


def test_javascript_renders_deprecation_metadata() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")

    for token in ["deprecation_reason", "replacement_id", "sunset_at"]:
        assert token in js
    for header in ["原因", "替代", "下架"]:
        assert re.search(rf"<th>\s*{re.escape(header)}\s*</th>", html)


def test_javascript_has_approval_workflow_handlers() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    assert "loadApprovals" in js
    assert "approveApproval" in js
    assert "rejectApproval" in js
    assert 'data-action="approve-approval"' in js
    assert 'data-action="reject-approval"' in js


def test_catalog_patch_ui_modules_exist() -> None:
    assert API_JS.is_file()
    assert CATALOG_EDITOR_JS.is_file()
    assert ROLLBACK_JS.is_file()
    assert ACTIONS_JS.is_file()


def test_catalog_patch_ui_controls_exist_in_html() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    for element_id in [
        "catalog-dry-run",
        "catalog-apply",
        "catalog-diff-preview",
        "catalog-patch-history-body",
        "catalog-editor-controls",
    ]:
        assert f'id="{element_id}"' in html
    assert 'data-action="catalog-enable-mcp"' in CATALOG_EDITOR_JS.read_text(encoding="utf-8")
    assert 'data-action="catalog-disable-mcp"' in CATALOG_EDITOR_JS.read_text(encoding="utf-8")
    rollback_source = ROLLBACK_JS.read_text(encoding="utf-8")
    assert "patch-rollback" in rollback_source
    assert "control-plane-rollback" in rollback_source


def test_catalog_patch_ui_references_patch_endpoints() -> None:
    api_js = API_JS.read_text(encoding="utf-8")
    rollback_js = ROLLBACK_JS.read_text(encoding="utf-8")

    assert "/catalog/{harness}/surfaces/patch" in api_js
    assert "catalogPatch" in CATALOG_EDITOR_JS.read_text(encoding="utf-8")
    assert "/patches" in api_js
    assert "/patches/{patch_id}/rollback" in api_js
    assert "patchRollback" in rollback_js


def test_catalog_enable_uses_operator_input_not_redacted_preview() -> None:
    # Catalog surface command_preview / url are redacted at storage time;
    # deriving an enable config from them would write "[REDACTED]" into the
    # real harness config. Enable must read operator-entered form values only.
    editor = CATALOG_EDITOR_JS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "command_preview" not in editor
    assert "buildMcpConfigFromRegistry" not in editor
    assert "configure-mcp-server" not in editor

    for element_id in [
        "catalog-enable-form",
        "catalog-enable-command",
        "catalog-enable-args",
        "catalog-enable-url",
        "catalog-enable-env",
        "catalog-enable-stage",
    ]:
        assert f'id="{element_id}"' in html


def test_index_html_loads_catalog_patch_modules_before_app_js() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    api_pos = html.index('src="api.js"')
    rollback_pos = html.index('src="ui/rollback.js"')
    catalog_pos = html.index('src="ui/catalog-editor.js"')
    config_pos = html.index('src="ui/config-editor.js"')
    profile_pos = html.index('src="ui/profile-editor.js"')
    registry_pos = html.index('src="ui/registry-editor.js"')
    actions_pos = html.index('src="ui/actions.js"')
    app_pos = html.index('src="app.js"')
    assert (
        api_pos
        < rollback_pos
        < catalog_pos
        < config_pos
        < profile_pos
        < registry_pos
        < actions_pos
        < app_pos
    )


def test_harness_config_patch_ui_modules_exist() -> None:
    assert CONFIG_EDITOR_JS.is_file()


def test_harness_config_patch_ui_controls_exist_in_html() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    for element_id in [
        "config-scope",
        "config-op",
        "config-path",
        "config-value",
        "config-dry-run",
        "config-apply",
        "config-diff-preview",
        "config-validation-errors",
        "config-patch-history-body",
    ]:
        assert f'id="{element_id}"' in html


def test_harness_config_patch_ui_references_patch_endpoints() -> None:
    api_js = API_JS.read_text(encoding="utf-8")
    editor = CONFIG_EDITOR_JS.read_text(encoding="utf-8")

    for endpoint in [
        "/harness-config/{harness_id}/patch",
        "/harness-config/{harness_id}/diff",
        "/harness-config/{harness_id}/explain",
    ]:
        assert endpoint in api_js
    assert "harnessConfigPatch" in editor
    assert "harnessConfigDiff" in editor
    assert "harnessConfigExplain" in editor


def test_harness_config_editor_optimistic_lock_and_cross_write_guard() -> None:
    editor = CONFIG_EDITOR_JS.read_text(encoding="utf-8")

    assert "base_mtime" in editor
    assert "stale_target" in editor
    assert 'basePath: "/harness-config"' in editor
    assert 'family: "harness"' in editor
    assert 'basePath: "/config"' not in editor.split("HARNESS_CONFIG_DESCRIPTOR")[0]


def test_profile_editor_ui_modules_exist() -> None:
    assert PROFILE_EDITOR_JS.is_file()


def test_profile_editor_controls_exist_in_html() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    for element_id in [
        "profile-name",
        "profile-harness-id",
        "profile-provider",
        "profile-model",
        "profile-scope",
        "profile-default-env",
        "profile-dry-run",
        "profile-apply",
        "profile-diff-preview",
        "profile-validation-errors",
        "profile-patch-history-body",
    ]:
        assert f'id="{element_id}"' in html


def test_profile_editor_references_profile_endpoints() -> None:
    api_js = API_JS.read_text(encoding="utf-8")
    editor = PROFILE_EDITOR_JS.read_text(encoding="utf-8")
    for endpoint in ["/profiles", "/profiles/{name}", "/projects/{project_path}/bind-profile"]:
        assert endpoint in api_js
    assert "profileDetail" in editor
    assert "base_mtime" in editor
    assert "stale_target" in editor
    assert "ENV_VAR_PATTERN" in editor or "A-Z][A-Z0-9_]" in editor


def test_registry_editor_ui_modules_exist() -> None:
    assert REGISTRY_EDITOR_JS.is_file()


def test_registry_editor_controls_exist_in_html() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    for element_id in [
        "registry-id",
        "registry-label",
        "registry-command",
        "registry-cwd-mode",
        "registry-dry-run",
        "registry-apply",
        "registry-diff-preview",
        "registry-validation-errors",
        "registry-validation-warnings",
        "registry-patch-history-body",
    ]:
        assert f'id="{element_id}"' in html


def test_registry_editor_references_registry_endpoints() -> None:
    api_js = API_JS.read_text(encoding="utf-8")
    editor = REGISTRY_EDITOR_JS.read_text(encoding="utf-8")
    for endpoint in ["/registry/agents", "/registry/agents/{id}/disable", "/registry/schema"]:
        assert endpoint in api_js
    assert "registryAgents" in editor
    assert "registrySchema" in editor
    assert "base_mtime" in editor
    assert "stale_target" in editor


def test_readme_documents_p3_usage_and_limits() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for token in [
        "Run P3 Shared Capability Catalog / Harness Launch Policy",
        "agentctl skills list",
        "agentctl mcp list",
        "agentctl policy evaluate",
        "Skills / MCP tab",
        "P3 does not start MCP servers",
        "P3 does not execute external tools",
        "Secrets must not be stored",
    ]:
        assert token in readme


def test_control_plane_editor_modules_exist() -> None:
    assert CONTROL_PLANE_EDITOR_JS.is_file()


def test_control_plane_editor_controls_exist_in_html() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'src="ui/control-plane-editor.js"' in html
    for element_id in [
        "control-plane-editor-controls",
        "control-plane-skill-form",
        "control-plane-mcp-form",
        "control-plane-policy-form",
        "cp-mcp-command",
        "cp-mcp-env",
        "control-plane-diff-preview",
        "control-plane-validation-errors",
    ]:
        assert f'id="{element_id}"' in html


def test_control_plane_editor_references_endpoints() -> None:
    api_js = API_JS.read_text(encoding="utf-8")
    editor = CONTROL_PLANE_EDITOR_JS.read_text(encoding="utf-8")
    rollback_js = ROLLBACK_JS.read_text(encoding="utf-8")
    for endpoint in [
        "/skills/{skill_id}/history",
        "/skills/{skill_id}/rollback",
        "/mcp/{server_id}/history",
        "/mcp/{server_id}/rollback",
        "/policy/{agent_id}/history",
        "/policy/{agent_id}/rollback",
    ]:
        assert endpoint in api_js
    assert "skillHistory" in editor
    assert "control-plane-rollback" in rollback_js
    assert "historyPath" in rollback_js
    assert "command_preview" not in editor or "never pre-fill" in editor.lower() or "重新輸入" in editor


def test_control_plane_mcp_edit_avoids_redacted_resubmit() -> None:
    editor = CONTROL_PLANE_EDITOR_JS.read_text(encoding="utf-8")
    assert "cp-mcp-command" in editor
    assert '[REDACTED]' in editor
    assert 'byId("cp-mcp-command").value = ""' in editor


def test_index_html_loads_control_plane_editor_before_app_js() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    cp_pos = html.index('src="ui/control-plane-editor.js"')
    app_pos = html.index('src="app.js"')
    assert cp_pos < app_pos
