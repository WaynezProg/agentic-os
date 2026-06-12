# 057 — Agentic Runtime Inventory (P37)

Status: Draft
Date: 2026-06-08
Depends on: `specs/054-tool-discovery-config-inventory.md` (P34), `specs/056-attach-resume-sessions.md` (P36)
Blocks: `specs/058-daily-operator-v2.md`

## Scope

| Owns | Does not own |
|------|--------------|
| OpenClaw/Hermes/n8n 的 read-only inventory | 啟動/停止 agentic runtime（永遠不做） |
| 顯示 skill / MCP / tool / flow 狀態 | 修改外部工具內部設定 |
| `GET /agentic/inventory` — 聚合式 inventory | n8n webhook 或執行 |
| UI：Agentic Runtime 區塊 | Vibe Coding 區塊（P35 已做） |

## Rationale

P34 做了工具偵測，P36 做了 session attach。P37 進一步讀取 agentic runtime 的 **能力清單**（skills、MCP servers、tools、flows），讓使用者在 dashboard 上看到「我的 agent 目前有哪些能力可用」。全部 read-only，不寫入外部工具。

## Domain model

新增 `AgenticInventoryResult` dataclass：

```python
@dataclass(frozen=True)
class AgenticInventoryResult:
    agent_id: str          # "openclaw", "hermes", "n8n"
    tool_kind: str         # "agentic_runtime"
    skills: list[SurfaceSummary]
    mcp_servers: list[McpSurfaceSummary]
    tools: list[ToolSummary]
    flows: list[FlowSummary]   # n8n only
    error: str | None = None
```

## Backend

### Module: `agentic_inventory.py`

- `build_agentic_inventory(agent_id: str, config_path: str) -> AgenticInventoryResult`
  - 根據 agent_id 分派到對應的 inventory reader
  - 每個 reader 是 read-only，不修改外部狀態

### Inventory readers

**OpenClaw (`_read_openclaw_inventory`):**
- 掃描 `~/.openclaw/` 目錄下的 skill definitions
- 讀 MCP server 設定（如有）
- 回傳 skills + mcp_servers 列表

**Hermes (`_read_hermes_inventory`):**
- 掃描 `~/.hermes/` 目錄下的 skill/tool definitions
- 讀 MCP server 設定
- 可選：透過 Hermes MCP bridge 呼叫 `tools/list` 取得 live tool list
- 回傳 skills + tools + mcp_servers

**n8n (`_read_n8n_inventory`):**
- 掃描 n8n config 目錄（`~/.n8n/`）
- 讀取 workflow JSON 列表
- 回傳 flows（workflow name + status active/inactive）

### API

- `GET /agentic/inventory` → `{agents: [{agent_id, tool_kind, skills, mcp_servers, tools, flows, error}]}`
  - 只回傳 `tool_kind == "agentic_runtime"` 的 agents
  - 每個 agent 的 inventory 獨立計算，某個 agent 失敗不影響其他
- `GET /agentic/inventory/{agent_id}` → 單一 agent 的 inventory
- 兩端點 read-only, localhost-only

### 與 catalog.py 的關係

P37 的 inventory 和現有 `catalog.py` 的 `scan()` 不同：
- `catalog.py` 掃描 **所有** harness（含 vibe coding）的 surfaces
- P37 專注 **agentic runtime** 的能力清單，包含 n8n flows 這種 catalog.py 不處理的類型
- P37 可以內部复用 `catalog.scan()` 作為其中一個資料來源，但不限於此

## UI

- 新增 `ui/agentic-inventory.js`
- 在 Vibe Coding tab 之外新增 Agentic Runtime 區塊（或獨立 tab）
- 每個 agentic agent 一個 card：
  - agent name + version + status
  - Skills list（name + enabled/disabled）
  - MCP servers list（name + status）
  - Tools list（name + type）
  - Flows list（n8n only: name + active/inactive）
- Error state：顯示 `parse_error` 而非 crash
- 全部 read-only，無 edit 按鈕

## Acceptance

1. `GET /agentic/inventory` 回傳所有 agentic_runtime agents 的 inventory
2. OpenClaw inventory 包含 skills + mcp_servers
3. Hermes inventory 包含 skills + tools + mcp_servers
4. n8n inventory 包含 flows（如果 n8n 已安裝）
5. 某個 agent 的 inventory 失敗不影響其他 agent（回傳 `error` 欄位）
6. UI 顯示 inventory cards，區分 skills/MCP/tools/flows
7. 所有端點 read-only, localhost-only
8. 不寫入任何外部工具設定
