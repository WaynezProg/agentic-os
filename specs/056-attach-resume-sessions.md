# 056 — Attach / Resume Existing Sessions (P36)

Status: Draft
Date: 2026-06-08
Depends on: `specs/055-vibe-coding-runtime-adapter.md` (P35)
Blocks: `specs/057-agentic-runtime-inventory.md`

## Scope

| Owns | Does not own |
|------|--------------|
| 掃描已在 CLI/Desktop 跑的 session 並綁定到 workspace | 啟動新 session（P35 已做） |
| 顯示外部 session 狀態 + evidence | 修改外部工具內部狀態 |
| `POST /sessions/{id}/attach` exec/preview | Filesystem sniff for session state |
| Agentic runtime attach（openclaw/hermes/opencode） | Agentic runtime launch（P37） |

## Rationale

Target persona 是 CLI 重度使用者——每天在 terminal 跑 Codex / Claude Code / OpenClaw / Hermes。這些 session 不是從 dashboard launch 的，但使用者想在大螢幕上看狀態、查 evidence、統一管理。P36 讓 dashboard 能「接管」已存在的 session。

## Domain model

`SessionRecord` 已有 attach 欄位（不需要改 schema）：
- `external_session_id: str | None`
- `attachable: bool`
- `attach_status: AttachStatus` (`none` / `available` / `attached` / `unsupported`)

需要擴充的是 `attach.py` 的 capability matrix：
- 新增 `_VIBE_CODING` set（claude/codex/cursor/opencode/qwen）
- 新增 `_AGENTIC` set（openclaw/hermes）
- 每個 set 有不同的 `parse_external_session_id` 邏輯和 `build_attach_command` 語法

## Backend

### 修改 `attach.py`

1. **新增 vibe coding session ID parser**
   - `parse_claude_session_id(stdout_log: Path) -> str | None`
     - Claude Code stdout 格式待確認（需要 smoke test）
     - 候選：parse `--session-id` flag output, 或 JSON metadata line
   - `parse_codex_session_id(stdout_log: Path) -> str | None`
     - Codex stdout 格式待確認
   - `parse_external_session_id` 分派到對應 parser（目前只處理 openclaw）

2. **新增 vibe coding attach command builder**
   - Claude Code: `claude --resume <session_id>` 或 `claude --continue`
   - Codex: `codex resume <session_id>` 或 `codex --session <session_id>`
   - 具體 flag 需要 smoke test 確認

3. **擴充 `evaluate_attach`**
   - 支援 vibe coding agents 的 attach 決策
   - 需要 external_session_id 才能 attach（同 agentic agents）

### 新增 API: Session Discovery

- `POST /sessions/discover` → 掃描外部 session
  - 輸入：`{workspace_path: str, agent_ids: list[str] | None}`
  - 掃描策略（依 agent 類型）：
    - **Vibe coding (claude/codex/cursor)**: 掃描 tool-specific log dirs（`~/.claude/projects/`、`~/.codex/log/`）找 recent session metadata
    - **Agentic (openclaw/hermes)**: 呼叫 MCP bridge API（`hermes conversations_list`、`openclaw` session list）
  - 回傳：`{discovered: [{external_session_id, agent_id, started_at, status_hint, workspace_match}]}`
  - **不走 filesystem sniff 猜測**——只掃 well-known metadata 位置或走 explicit API

- `POST /sessions/{id}/attach` — 已存在，需確認 exec mode 正確串接新 parsers
  - `mode: "preview"` → 回傳 attach command 不執行
  - `mode: "exec"` → 執行 attach command，更新 session 狀態

### 新增 Session → Workspace Binding

- `PUT /sessions/{id}/workspace` → `{workspace_path: str}`
  - 將 external session 綁定到 workspace
  - 更新 session metadata（在 store 加 `workspace_path` 欄位）

### Storage 變更

- `sessions` table 新增 `workspace_path TEXT` column（nullable）
- Migration: `ALTER TABLE sessions ADD COLUMN workspace_path TEXT`

### UI: Attach Surface

- 新增 `ui/session-attach.js`
- 流程：
  1. 選 workspace（或 active workspace）
  2. 點「Scan Sessions」→ `POST /sessions/discover`
  3. 顯示 discovered sessions 列表：agent_id + external_session_id + started_at + status hint
  4. 每個 session 可「Bind」→ 建立 agentic-os session record + 綁定 workspace
  5. Bound session 出現在一般 session list，可查看 status / log / evidence
  6. 可選「Attach」→ `POST /sessions/{id}/attach` (exec mode)

### Evidence 來源（外部 session）

外部 session 的 evidence 來源與 daemon-spawned 不同：

| 來源 | daemon-spawned | external (attached) |
|------|---------------|-------------------|
| stdout/stderr | JsonlLogStore (supervisor tee) | 不存在（或從 tool log 匯入） |
| metadata | SessionRecord | 從 attach preview 解析 |
| tool-specific logs | 不讀 | 未來可匯入（不在 P36 scope） |

**P36 限制**：external session 沒有 stdout/stderr JSONL（因為不是 daemon spawn 的）。Evidence bundle 只包含 metadata + events。如果需要完整 log，使用者要手動匯入或等後續 phase。

## Acceptance

1. `POST /sessions/discover` 能掃描指定 workspace 的外部 session
2. 掃描結果顯示 external_session_id + agent_id + started_at
3. Bind 操作建立 agentic-os session record 並綁定 workspace
4. Bound session 出現在一般 session list
5. `POST /sessions/{id}/attach` preview 回傳正確 attach command
6. `POST /sessions/{id}/attach` exec 執行 attach command（如果 tool 支援）
7. Vibe coding attach（claude/codex）至少 preview 可用
8. Agentic attach（openclaw/hermes）exec 可用（既有功能維持）
9. 不讀取 API keys / tokens
10. 所有現有測試持續通過

## Out of scope（明確不做）

- 從外部 tool 匯入完整 stdout/stderr log
- 雙向 sync（agentic-os session 狀態 ↔ 外部 tool 狀態）
- 自動發現（每次開啟 dashboard 自動 scan）——保留手動觸發
- External session 的 evidence zip 包含 tool-specific logs
