# 055 — Vibe Coding Runtime Adapter (P35)

Status: Draft
Date: 2026-06-08
Depends on: `specs/054-tool-discovery-config-inventory.md` (P34)
Blocks: `specs/056-attach-resume-sessions.md`

## Scope

| Owns | Does not own |
|------|--------------|
| Codex + Claude Code 真實 launch / stop / log / evidence 從 UI 操作 | Agentic runtime 啟動（P37） |
| UI：workspace → profile/model → launch → session/log → stop/retry | Chat UI（永遠不做） |
| Vibe coding surface（獨立 UI entry point） | Agentic runtime surface |
| Evidence bundle 產生（JSONL + metadata） | 外部工具內部行為 |

## Rationale

這是產品能不能用的核心。目標：從 UI 選 workspace → 選 profile/model → launch Codex 或 Claude Code → 看到 session 狀態和 log → stop / retry → 拿到 evidence bundle。現有 `registry.py` + `supervisor.py` + `evidence.py` 已支援 daemon-spawned session 的完整 lifecycle，P35 是前端串接 + 確認 vibe coding agents 的 adapter 正確。

## Backend

### 前置確認（現有功能，不需要新建）

- `POST /sessions` — launch session with agent_id + cwd + message + profile/model ✓
- `POST /sessions/{id}/stop` — stop via process_group ✓
- `POST /sessions/{id}/retry` — retry with policy gate ✓
- `GET /sessions/{id}` — session status ✓
- `GET /sessions/{id}/logs/{stream}` — JSONL log read ✓
- `GET /sessions/{id}/evidence` — evidence bundle ✓
- `GET /sessions/{id}/evidence/zip` — zip download ✓

### 需要新增 / 修改

1. **`attach.py` — 擴充 `_SUPPORTED` 含 codex/claude**
   - 將 `claude`、`codex`、`cursor` 從 `_UNSUPPORTED` 移到新分類
   - 新增 `_VIBE_CODING = frozenset({"claude", "codex", "cursor", "opencode", "qwen"})`
   - 修改 `parse_external_session_id` 支援 claude/codex stdout format
   - 修改 `build_attach_command` 支援 claude/codex attach 語法

2. **`AgentDefinition` — 新增 `tool_kind` 欄位**（從 P34 帶過來）
   - 預設推導邏輯：`_derive_tool_kind(agent_id)` based on known mapping

3. **`POST /sessions` — 確認 vibe coding agents launch 路徑正確**
   - claude: `claude -p "{{message}}" --output-format text [--model {{model}}]`
   - codex: `codex exec "{{message}}" [--model {{model}}]`
   - 需要確認 `model_arg` template substitution 正確

### UI: Vibe Coding Surface

- 新增 `ui/vibe-coding-launcher.js`
- 流程：
  1. 選 workspace（從 `GET /workspaces` list）
  2. 選 agent（僅顯示 `tool_kind == vibe_coding` 且 `installed == true`）
  3. 選 profile / model / provider（從 `GET /profiles` + `GET /workspaces/dashboard`）
  4. 輸入 message
  5. `POST /sessions` launch
  6. 顯示 session 列表：status pill + agent_id + cwd + model + started_at
  7. 點進 session：顯示 log（streaming）、stop / retry 按鈕
  8. 完成後：evidence bundle 下載按鈕

### Evidence 來源

Vibe coding sessions 的 evidence 來源統一：
- **stdout/stderr**: JSONL logs via `JsonlLogStore`（supervisor 已實作 tee）
- **metadata**: session record（agent_id、cwd、model、provider、profile）
- **外部 session ID**: `parse_external_session_id` 從 stdout 解析（P34 擴充）

**不做**：讀取外部工具自己的 log 檔（如 `~/.claude/projects/`），這屬於 P36 attach 範圍。

## Acceptance

1. UI 可以從 workspace → profile → launch 啟動 Codex / Claude Code session
2. Session 狀態即時更新（queued → running → succeeded/failed/stopped）
3. Log 在 UI 上可讀（stdout + stderr 分開顯示）
4. Stop 按鈕正確終止 process group
5. Retry 按鈕走 policy gate 重新 launch
6. Evidence bundle 可下載（zip）
7. `tool_kind` 欄位正確區分 vibe_coding / agentic_runtime
8. UI 只顯示已安裝的 vibe coding agents（依賴 P34 discovery 結果）
9. 所有現有測試持續通過（不 break daemon-spawned session lifecycle）
