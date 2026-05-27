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


def test_javascript_references_required_daemon_endpoints() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    for endpoint in [
        "/health",
        "/agents",
        "/sessions",
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
