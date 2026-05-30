# 009 — Workflow Surface Catalog (P6)

Status: Draft
Date: 2026-05-30

## Positioning

P6 將 Claude Code、OpenClaw、Hermes 等 harness 的 workflow surface（hooks、slash commands、skills、subagents、MCP servers）變成 agentic-os 可掃描、可顯示、可比對的 catalog。

P6 是**只讀 catalog**：掃描並記錄 workflow surface 的存在與來源，不執行任何 harness-internal 邏輯，不改寫設定檔，不觸發 hooks 或 commands。

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P6 | workflow surface scan and catalog | inventory of hooks/commands/skills/subagents/MCP across harness scopes | scan paths, classify surfaces, show merged view per project, diff between scopes | executing hooks, loading skills, starting MCP servers, modifying configs |

## Motivation

目前 agentic-os 管理 harness instance profile（P4）和設定範圍（P5），但**看不到**每個 project 實際會啟用哪些 workflow surface。開發者需要手動翻找 `.claude/`、`.openclaw/`、`.hermes/` 目錄，或從 harness 啟動後的日誌中推斷。

P6 解決以下問題：

- 這個 project 裡，Claude Code 有哪些 hooks？
- 哪些 skill 會啟用？哪個 skill 來自 user scope vs. project scope？
- 哪個 subagent 有 write 權限？
- 哪個 MCP server 會被接上？
- OpenClaw 和 Claude Code 的 capability 有沒有重疊或衝突？

## Scope

### 1. Scan Paths

P6 定義可掃描的目錄路徑，按 scope 分層：

| Scope | Claude Code | OpenClaw | Hermes |
|-------|-------------|----------|--------|
| managed | (系統層級，由 harness 控制) | (系統層級) | (系統層級) |
| user | `~/.claude/settings.json` | `~/.openclaw/config.toml` | `~/.hermes/config.toml` |
| project | `<repo>/.claude/settings.json` | `<repo>/.openclaw/config.toml` | `<repo>/.hermes/config.toml` |
| local | `<repo>/.claude/local/` | `<repo>/.openclaw/local/` | `<repo>/.hermes/local/` |

每個 scope 可包含以下子目錄：

| Path | Content |
|------|---------|
| `settings.json` / `config.toml` | hooks, MCP servers, permissions, model config |
| `commands/` | slash commands（`.md` 或 `.toml`） |
| `skills/` | skill definitions（`SKILL.md` + `agent-workspace/`） |
| `agents/` | subagent definitions |
| `memory/` | persistent memory files（只記錄存在與行數，不讀取內容） |

### 2. Surface Classification

掃描結果按類型分類：

| Type | Description | Source fields |
|------|-------------|---------------|
| `hook` | settings.json 中的 hooks 設定（PreToolUse、PostToolUse 等） | `name`, `matcher`, `hooks[]` |
| `command` | commands/ 目錄下的 slash command | `name`, `description`, `file_path` |
| `skill` | skills/ 目錄下的 skill | `name`, `description`, `scope` (user/project/local) |
| `subagent` | agents/ 目錄或 settings.json 中的 subagent | `name`, `tools`, `write_permission` |
| `mcp_server` | settings.json 或 config 中的 MCP server 定義 | `name`, `transport`, `scope` |
| `permission` | settings.json 中的 permission 設定 | `type`, `pattern`, `action` |

每個 surface record 包含：

```text
id:         "<type>:<name>@<scope>"
type:       hook | command | skill | subagent | mcp_server | permission
name:       surface name
scope:      user | project | local | managed
harness:    claude | openclaw | hermes
source:     absolute file path
enabled:    boolean
metadata:   type-specific fields
```

### 3. Merge & Conflict Resolution

多個 scope 可定義同一個 surface（例如 user skill 和 project skill 同名稱）。P6 提供 merged view：

- **Project scope 覆蓋 user scope**（與 harness 行為一致）
- **Local scope 覆蓋 project scope**
- 衝突時記錄 `overridden_by: <scope>` 和 `overrides: <scope>`
- `agentctl catalog merged <harness> --cwd <dir>` 回傳最終生效的 surfaces

### 4. Diff

比較不同 scope 之間或不同 project 之間的 surface 差異：

```bash
# 比較 user vs project scope 中 Claude Code 的 surfaces
agentctl catalog diff claude --scope user --scope project

# 比較兩個 project 的 surfaces
agentctl catalog diff claude --cwd ~/project-a --cwd ~/project-b
```

Diff 輸出包含：
- `added`: 在 B 有、在 A 沒有的 surface
- `removed`: 在 A 有、在 B 沒有的 surface
- `modified`: 同名但定義不同的 surface

### 5. CLI Commands

```bash
# 列出單一 project 中某 harness 的所有 surfaces
agentctl catalog list claude --cwd ~/project
agentctl catalog list claude --cwd ~/project --type skill
agentctl catalog list openclaw --cwd ~/project

# 列出 merged view（最終生效的 surfaces）
agentctl catalog merged claude --cwd ~/project

# 比較 scopes 或 projects
agentctl catalog diff claude --scope user --scope project
agentctl catalog diff claude --cwd ~/project-a --cwd ~/project-b

# 顯示單一 surface 的詳細資訊
agentctl catalog show claude:skill:graphify --cwd ~/project
```

### 6. API Endpoints

```
GET /catalog/{harness}/surfaces
  ?cwd=<path>&scope=<scope>&type=<type>

GET /catalog/{harness}/surfaces/{surface_id}

GET /catalog/{harness}/merged
  ?cwd=<path>

GET /catalog/{harness}/diff
  ?cwd_a=<path>&cwd_b=<path>
  &scope_a=<scope>&scope_b=<scope>
```

### 7. UI Integration

Dashboard v2（P9）的 Workflow Surfaces tab：
- 按 type 分組顯示 surfaces
- 標註來源 scope（user/project/local）
- 高亮衝突和覆蓋
- 可搜尋、可過濾

## Out of Scope

- **不執行 hooks、commands、skills** — 只掃描和分類
- **不修改設定檔** — 只讀
- **不解析 harness-internal prompt routing 或 tool execution 邏輯**
- **不管理 credentials 或 secrets**
- **不做 live MCP server process 管理**

## Acceptance Criteria

- `agentctl catalog list claude --cwd <dir>` 回傳該 project 中 Claude Code 的 surfaces
- `agentctl catalog merged claude --cwd <dir>` 回傳最終生效的 surfaces（含 scope 覆蓋資訊）
- `agentctl catalog diff claude --scope user --scope project` 回傳 scopes 間的差異
- scan 不到不存在的目錄時不報錯，回傳空列表
- 同一個 surface 在多個 scope 都有定義時，正確標記 `overridden_by`
- 測試涵蓋：空目錄、單一 scope、多 scope 衝突、不存在的路徑

## Compatibility with Existing P5/P6 Features

P5 (fleet health probes)、P5 (drift detection)、P6 (governance audit)、P6 (deprecation lifecycle)、P8 (SLO benchmark)、P9 (deprecation metadata) 的既有功能維持不變，作為 agentic-os 的 fleet management 能力繼續運作。P6 workflow surface catalog 是**額外的** catalog layer，不影響既有 API 或行為。
