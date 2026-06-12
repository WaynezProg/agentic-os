# P42 MCP Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-tool MCP server matrix with safe copy/remove actions — the project's first write path into real tool configs, riding P10 SafeEditEngine end to end.

**Architecture:** `mcp_alignment.py` owns the per-tool path table, canonical translation adapters, and PatchTarget/PatchOp builders; endpoints orchestrate (pre-parse guard → SafeEditEngine.apply → keys-only response); UI renders matrix + two-step confirm. Values never cross the API boundary.

**Tech Stack:** Python 3.12, P10 SafeEditEngine (`merge`/`remove` ops, atomic json/toml writes, backup+audit), jsonschema registry, static JS UI.

**Spec/contracts:** `docs/superpowers/specs/2026-06-12-mcp-alignment-design.md` §3 — path table, `CanonicalServer`, function signatures, endpoint shapes, UI behavior. Confirmed facts: PatchEngine ops are `merge`+`remove` (no `set`); `_load_document` returns `{}` for missing OR unparseable files → endpoints MUST pre-check "target exists but unparseable" and refuse with 400 (data-loss guard; backup would save the day but we refuse anyway).

---

## File map

- Create: `src/agentic_os/mcp_alignment.py`, `tests/test_mcp_alignment.py`
- Create: `src/agentic_os/schemas/gemini/mcp_server@v1.json`
- Modify: `src/agentic_os/schema_registry.py` (gemini entry; opencode prefixes `("mcpServers", "mcp")`), `src/agentic_os/schemas/opencode/mcp_server@v1.json` (model real `mcp` key), `tests/test_schema_registry.py` or wherever whitelist is tested
- Modify: `src/agentic_os/api.py` (3 endpoints), `tests/test_api.py`
- Modify: `src/agentic_os/client.py`, `src/agentic_os/cli.py`, `tests/test_cli.py`
- Modify: `apps/web/api.js`, `apps/web/ui/tool-discovery.js`, `apps/web/styles.css`, `tests/test_web.py`
- Create: `specs/062-mcp-alignment.md`; Modify `README.md`, `CLAUDE.md`

### Task 1: `mcp_alignment.py` core (TDD)

- [ ] RED `tests/test_mcp_alignment.py` — fixture `_make_home(tmp_path)` seeds: claude `~/.claude.json` mcpServers {github: {command,args,env:{TOKEN:"sk-FAKE"}}, linear: {url}}, codex config.toml `[mcp_servers.context7]`, opencode opencode.json mcp {chrome: {type:"local", command:["npx","-y","pkg"], enabled:true}}, gemini/qwen/cursor minimal. Tests:
  - `test_read_server_names_per_tool`
  - `test_canonical_roundtrip_mcpservers_family` (claude→canonical→gemini identical fields)
  - `test_canonical_opencode_array_command_both_ways` (command list ↔ command+args, environment↔env, enabled added on write)
  - `test_canonical_remote_url_server`
  - `test_extras_preserved_within_family_only`
  - `test_unsupported_shape_raises` (no command, no url)
  - `test_build_copy_patch_ops` (op=="merge", path `mcpServers.github` / `mcp.github` / `mcp_servers.github` per target, PatchTarget file/format from table)
  - `test_build_remove_patch_ops` (op=="remove")
  - `test_summarize_def_keys_only` ("sk-FAKE" not in json.dumps(summary); env shows key names)
  - `test_target_unparseable_detected` (`target_config_parse_error(tool, home)` returns error string for corrupt file, None for valid/missing)
- [ ] GREEN: implement per design §3.1 + `target_config_parse_error` helper; ruff; commit `feat(P42): mcp_alignment canonical adapters + patch builders`

### Task 2: schema registry additions (TDD)

- [ ] RED: find existing whitelist tests (`grep -rn "is_path_allowed" tests/`) and add: gemini mcpServers allowed for kind mcp_server; opencode `mcp.foo` allowed AND legacy `mcpServers.foo` still allowed; gemini schema validates a doc `{mcpServers: {x: {command: "a"}}}` with no errors
- [ ] GREEN: whitelist entries + `schemas/gemini/mcp_server@v1.json` (copy of claude's) + opencode schema gains `mcp` property (type/command array/enabled, additionalProperties true). Full existing suite stays green. Commit `feat(P42): schema registry covers gemini + opencode real mcp shape`

### Task 3: endpoints + client + CLI (TDD)

- [ ] RED `test_api.py` (`_make_alignment_client(tmp_path)` = capability fixture home + create_app(capability_home=home)):
  - `test_mcp_matrix_endpoint` (union, per-tool booleans, sorted by coverage desc)
  - `test_mcp_copy_dry_run_default_no_write` (response applied=False; target file unchanged on disk)
  - `test_mcp_copy_apply_writes_target` (apply → target parses, server present, source untouched, backup info in response, patch_id non-null)
  - `test_mcp_copy_to_codex_toml_roundtrip` (tomllib re-reads written file)
  - `test_mcp_copy_conflicts` (404 unknown source server / unknown tool 400 / 409 already in target)
  - `test_mcp_copy_refuses_unparseable_target` (corrupt target json → 400, file bytes unchanged)
  - `test_mcp_remove_apply` + 404
  - `test_mcp_responses_never_contain_values` (fixture secret absent from all response texts)
- [ ] RED `test_cli.py`: FakeClient methods `mcp_matrix`, `mcp_copy(server, from_tool, to_tool, apply)`, `mcp_remove(tool, server, apply)`; commands print summary; default dry-run passes `apply=False`
- [ ] GREEN: api.py — `GET /tools/mcp/matrix`, `POST /tools/mcp/copy`, `POST /tools/mcp/remove` (Pydantic models `McpCopyRequest{server,from_tool,to_tool,dry_run=True}`, `McpRemoveRequest{tool,server,dry_run=True}`); wire `safe_edit_engine` + `capability_home`; client methods; `agentctl tools mcp-matrix|mcp-copy|mcp-remove` with `--apply`. Commit `feat(P42): mcp matrix/copy/remove endpoints + CLI (dry-run default)`

### Task 4: UI matrix + two-step actions

- [ ] RED `test_web.py`: api.js `mcpMatrix`/`mcpCopy`/`mcpRemove`; tool-discovery.js `renderMcpMatrix`, `mcp-matrix-table`, `data-mcp-copy`, `data-mcp-remove`, confirm modal marker `mcp-confirm`; styles `.mcp-matrix-table`, `.mcp-drift`
- [ ] Implement in tool-discovery.js below capabilities: matrix table (drift rows highlighted), ✗ cell → copy button (source dropdown when >1), ✓ cell → remove; click → dry-run call → modal with keys-only summary + backup path + active-session warning (fetch `/sessions/live?within_hours=1` and flag target tool active) → confirm → apply → refresh capabilities+matrix. `node --check`; pytest web green. Commit `feat(P42): MCP alignment matrix UI with two-step safe actions`

### Task 5: verification + docs + ship

- [ ] `uv run pytest -q` + `uv run ruff check .` all green
- [ ] Fixture-home end-to-end: copy claude→gemini apply → parse target → patches rollback (existing P10 rollback CLI) restores original — run for real in /tmp
- [ ] Real machine: daemon restart → `agentctl tools mcp-matrix` against real configs (read-only); one `mcp-copy --from claude --to gemini --server <pick>` **without** `--apply` (dry-run only; user's real configs untouched); browser: matrix renders, drift highlight, modal opens with keys-only summary
- [ ] `specs/062-mcp-alignment.md`; README + CLAUDE.md P42 rows; commit docs; push; update PR #15 body with P42 section

## Self-review

- Spec §3.1→Task 1, §3.2→Task 2, §3.3/3.4→Task 3, §3.5→Task 4, §4/§5→Tasks 1-5. Covered.
- Op-name fact (merge/remove) baked into Task 1 assertions; unparseable-target guard has both unit (Task 1) and endpoint (Task 3) tests.
- No values-leak: dedicated assertions at module (Task 1), API (Task 3) layers.
