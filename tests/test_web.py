from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "apps" / "web"
INDEX_HTML = WEB_DIR / "index.html"
STYLES_CSS = WEB_DIR / "styles.css"
APP_JS = WEB_DIR / "app.js"


def test_static_web_files_exist() -> None:
    assert INDEX_HTML.is_file()
    assert STYLES_CSS.is_file()
    assert APP_JS.is_file()


def test_five_tabs_are_present() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert html.count('role="tab"') == 5
    for tab in ["Agents", "Sessions", "Logs", "Memory", "Skills / MCP"]:
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

    assert 'id="agents-table"' in html
    assert 'id="agents-body"' in html
    for header in ["ID", "Label", "Enabled", "CWD mode", "Stop policy", "Command preview"]:
        assert re.search(rf"<th>\s*{re.escape(header)}\s*</th>", html)


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


def test_skills_mcp_placeholder_panels_exist() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="panel-skills"' in html
    assert 'id="skills-table"' in html
    assert 'id="skills-body"' in html
    assert 'id="mcp-table"' in html
    assert 'id="mcp-body"' in html


def test_javascript_references_required_daemon_endpoints() -> None:
    js = APP_JS.read_text(encoding="utf-8")

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
    ]:
        assert endpoint in js


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
        r'if \(action === "logs" && sessionId\) \{(?P<body>.*?)\n    \} else if',
        js,
        re.DOTALL,
    )
    assert match is not None
    logs_action_body = match.group("body")

    assert 'byId("load-logs").addEventListener("click", loadLogs)' in js
    assert "function showTab(tabName, options = {})" in js
    assert 'showTab("logs", { skipLoad: true });' in logs_action_body
    assert logs_action_body.count("loadLogs(") == 1
    assert re.search(r"if \(!options\.skipLoad\) \{\s*loadActiveTab\(\);\s*\}", js)


def test_no_node_build_or_package_requirement_is_introduced() -> None:
    for path in [
        WEB_DIR / "package.json",
        WEB_DIR / "package-lock.json",
        WEB_DIR / "pnpm-lock.yaml",
        WEB_DIR / "yarn.lock",
        WEB_DIR / "node_modules",
    ]:
        assert not path.exists()

    combined = INDEX_HTML.read_text(encoding="utf-8") + APP_JS.read_text(encoding="utf-8")
    for token in ["vite", "webpack", "parcel", "npm install", "node_modules"]:
        assert token not in combined.lower()
