# P40 Capability Radar + P41 Transcript Preview + Desktop Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface real skills/MCP/plugins/memory per tool, add session transcript preview, and fix desktop GUI-launch PATH so the app connects on open.

**Architecture:** Same observe-first pattern as P39: read-only scanner module → injectable-root GET endpoint → CLI → static UI card. Desktop fix is two surgical changes (Rust PATH list + launch script) verified with `env -i` clean-PATH simulation.

**Tech Stack:** Python 3.12 / FastAPI / Typer, tomllib + json parsers (no regex on configs), static JS UI, pytest + cargo test.

**Spec/contracts:** `docs/superpowers/specs/2026-06-12-capability-radar-design.md` §2 — `ToolCapabilities` / `MemoryFileInfo` dataclasses, per-tool path table, transcript endpoint contract. The design doc is the schema source of truth; this plan defines tasks, files, and test cases.

---

## File map

- Create: `src/agentic_os/capability_inventory.py`, `tests/test_capability_inventory.py`
- Modify: `src/agentic_os/live_sessions.py` (+`read_transcript_tail`), `tests/test_live_sessions.py`
- Modify: `src/agentic_os/api.py` (`GET /tools/capabilities`, `GET /sessions/live/transcript`, `create_app(capability_home=…)`), `tests/test_api.py`
- Modify: `src/agentic_os/client.py`, `src/agentic_os/cli.py`, `tests/test_cli.py`
- Modify: `apps/web/api.js`, `apps/web/ui/tool-discovery.js`, `apps/web/ui/dashboard-v2.js`, `apps/web/styles.css`, `apps/web/index.html` (overview section order), `tests/test_web.py`
- Modify: `apps/desktop/src-tauri/src/daemon.rs` (ensure_path_dirs + test), `scripts/desktop-daemon.sh` (drop `rtk`)
- Create: `specs/060-capability-radar.md`, `specs/061-transcript-preview.md`; Modify `README.md`, `CLAUDE.md`

### Task 1: `capability_inventory.py` (TDD)

- [ ] Write failing tests in `tests/test_capability_inventory.py` with a `_make_home(tmp_path)` fixture builder that creates minimal real-shaped configs:
  - claude: `home/.claude/skills/{browse,tdd}/`, `home/.claude.json` `{"mcpServers": {"github": {"command": "x", "env": {"TOKEN": "sk-FAKE"}}}}`, `home/.claude/plugins/cache/official/`, `home/.claude/CLAUDE.md`
  - codex: `home/.codex/config.toml` with `[mcp_servers.context7]\ncommand = "npx"`, `home/.codex/AGENTS.md` as symlink → real file
  - gemini/qwen/opencode/cursor analogous per design table
  - Cases: `test_claude_capabilities_basic` (skills/mcp/plugins/memory extracted), `test_missing_tool_reports_present_false`, `test_bad_json_reports_error_not_crash`, `test_secret_values_never_in_output` (assert `"sk-FAKE"`/`"npx"` not in `json.dumps(asdict(...))`), `test_codex_toml_mcp_names`, `test_codex_agents_md_symlink_stat`, `test_oversized_config_skipped` (>20MB guard via small injected cap), `test_read_all_capabilities_order`
- [ ] Verify RED → implement `capability_inventory.py`: `MemoryFileInfo`, `ToolCapabilities`, `capabilities_dict()`, per-tool readers `_read_claude/_read_codex/_read_gemini/_read_qwen/_read_opencode/_read_cursor(home)`, `read_all_capabilities(home: Path | None = None)` (default `Path.home()`), `_MAX_CONFIG_BYTES = 20MB` guard, every reader wrapped so failure → `error` field
- [ ] GREEN + ruff + commit `feat(P40): capability_inventory readers for real tool configs`

### Task 2: `GET /tools/capabilities` + CLI (TDD)

- [ ] RED in `test_api.py`: `_make_capability_client(tmp_path)` building tmp home + `create_app(..., capability_home=home)`; assert tools list, claude entry fields, `generated_at`; secret-value absence end-to-end
- [ ] RED in `test_cli.py`: FakeClient `tools_capabilities()` + `agentctl tools capabilities` table run
- [ ] Implement: import + `capability_home` param on `create_app`, endpoint after `/tools/inventory`; `client.tools_capabilities()`; cli — reuse existing `tools` Typer group if present else create; GREEN + commit `feat(P40): /tools/capabilities endpoint + CLI`

### Task 3: transcript tail parser + endpoint (TDD, P41)

- [ ] RED in `test_live_sessions.py`: `read_transcript_tail(path, tool, limit)` — claude fixture (user + assistant + noise lines) → ordered messages with roles/text/timestamps; codex fixture (`user_message`/`agent_message`/response_item) → same; `test_transcript_tail_reads_only_tail` (large file, seek window); `test_transcript_skips_non_prompt_noise`
- [ ] RED in `test_api.py`: `GET /sessions/live/transcript` happy path (log under root); 400 for path outside roots; 400 for non-`.jsonl`; limit clamp
- [ ] Implement in `live_sessions.py`: `_TAIL_BYTES = 256*1024`, `read_transcript_tail(path: Path, tool: str, limit: int = 50) -> list[dict]` reusing `_is_real_prompt`/`_truncate`-style helpers (transcript text cap 2000 chars, separate `_clip`); endpoint in `api.py` validating `resolved.is_relative_to(root)` against configured roots and suffix check; GREEN + commit `feat(P41): transcript tail preview endpoint`

### Task 4: UI — capabilities cards, transcript panel, overview order

- [ ] RED in `test_web.py`: api.js has `toolCapabilities` + `liveTranscript`; tool-discovery.js has `renderCapabilities`/`capability-card`; dashboard-v2.js has `transcript-row`/`loadTranscript`; index.html overview panel has `#dashboard-v2` before the workspace dashboard section; CSS has `.capability-card`, `.transcript-row`
- [ ] Implement:
  - api.js endpoints; tool-discovery.js: after discovery/inventory render, fetch capabilities → per-tool card with count chips (`skills 100`, `mcp 12`, …) and first-8 name chips + `+N`
  - dashboard-v2.js: title cell click → toggle `<tr class="transcript-row"><td colspan=6>` panel; fetch transcript with `tool` + `log_path` from row dataset; render last 20 as `role: text` chat lines; loading + error states
  - index.html: move `#dashboard-v2` section to top of `#panel-overview`
- [ ] `node --check` both JS files; pytest test_web GREEN; commit `feat(P40-P41): capabilities cards + transcript preview UI, radar first on overview`

### Task 5: desktop PATH fix

- [ ] RED: Rust test `ensure_path_includes_homebrew_dirs` in daemon.rs `#[cfg(test)]` (input PATH `/usr/bin:/bin` → output contains `/opt/homebrew/bin` and `/usr/local/bin`)
- [ ] Implement: extend `required` array; drop `rtk` in `scripts/desktop-daemon.sh` start (`nohup uv run agentd serve …`)
- [ ] Verify: `cargo test` in `apps/desktop/src-tauri` passes; clean-PATH simulation: stop any daemon on :8767, `env -i HOME="$HOME" PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin" bash scripts/desktop-daemon.sh start` → health ok (homebrew dir present = what hardened_path now guarantees)
- [ ] Commit `fix(desktop): GUI-launch PATH lacks homebrew dirs; drop rtk from daemon launch`

### Task 6: docs + full verification + ship

- [ ] `specs/060-capability-radar.md`, `specs/061-transcript-preview.md`; README rows P40/P41; CLAUDE.md module map + dual-track table rows
- [ ] `uv run pytest -q` all green; `uv run ruff check .`; live: daemon + `/tools/capabilities` against real home shows claude 100 skills; browser cold-load: overview radar first, click row → transcript renders
- [ ] Push (PR #15 auto-updates); update PR body with P40/P41 + desktop fix section

## Self-review

- Spec coverage: design §2 P40→Tasks 1-2, P41→Task 3-4, desktop→Task 5, ordering→Task 4, docs→Task 6. No gaps.
- Contracts live in the design doc §2 (single source); test names enumerate behaviors; security cases (traversal, secret leakage) are explicit test cases in Tasks 1-3.
