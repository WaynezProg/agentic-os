# 054 — Tool Discovery + Config Inventory (P34)

Status: Draft
Date: 2026-06-08
Depends on: P33 (daily operator dashboard), workspace manager (P29)
Blocks: `specs/055-vibe-coding-runtime-adapter.md`, `specs/056-attach-resume-sessions.md`

## Scope

| Owns | Does not own |
|------|--------------|
| `tool_discovery.py` — 掃描 well-known 路徑 + `which` 偵測工具存在性 | 雙向 config sync |
| `config_inventory.py` — 讀 non-secret 設定（model、provider、config path） | 讀 API keys / tokens / session state |
| `GET /tools/discovery` — 列出偵測結果 | 寫入任何外部工具設定 |
| `GET /tools/inventory` — 列出每個工具的 config 摘要 | filesystem sniff for active sessions |
| `tool_kind` domain field (`vibe_coding` / `agentic_runtime`) | Harness 內部行為控制 |
| UI：read-only 工具清單（找到/沒找到/設定來源/目前模型） | 啟動、停止、attach |

## Rationale

雙軌產品（Vibe Coding Harness vs Agentic Runtime）的第一步：讓使用者知道「系統上看到哪些工具、各自什麼狀態」。讀取邊界必須嚴格——只做偵測 + non-secret prefill，一旦碰 sync 就是無底洞。

## Domain model

新增 `ToolKind` 欄位至 `AgentDefinition`（agents.toml 每筆 agent）：

```python
ToolKind = Literal["vibe_coding", "agentic_runtime"]
```

agents.toml 對照表：

| agent_id | tool_kind |
|----------|-----------|
| claude | vibe_coding |
| codex | vibe_coding |
| cursor | vibe_coding |
| opencode | vibe_coding |
| qwen | vibe_coding |
| openclaw | agentic_runtime |
| hermes | agentic_runtime |
| shell | (no kind — internal test agent) |

## Backend

### Module: `tool_discovery.py`

- `detect_tool(agent_id: str) -> ToolDiscoveryResult`
  - 跑 `which <binary>` 或檢查 well-known path（`~/.claude/`、`~/.codex/`、`/Applications/Cursor.app`）
  - 回傳 `{installed: bool, binary_path: str | None, version: str | None, version_error: str | None}`
- `discover_all(registry: Registry) -> list[ToolDiscoveryResult]`
  - 遍歷 registry 所有 enabled agent，呼叫 `detect_tool`
  - 結果 cache 5 分鐘（避免每次 API call 都 fork subprocess）

### Module: `config_inventory.py`

- `read_config_summary(agent_id: str, config_path: str) -> ConfigSummary`
  - 讀 `config_path` 下的 non-secret 設定
  - 回傳 `{config_source: str, model: str | None, provider: str | None, system_prompt_path: str | None, parse_error: str | None}`
  - **明確不讀**：API keys、auth tokens、session state
- 每個工具一個 reader function（`_read_claude_config`、`_read_codex_config` 等）
- `stability_contract` 機制：reader 遇到 unknown schema 回 `parse_error`，不 silent fallback

### API

- `GET /tools/discovery` → `{tools: [{agent_id, tool_kind, installed, binary_path, version, version_error}]}`
- `GET /tools/inventory` → `{tools: [{agent_id, tool_kind, config_source, model, provider, system_prompt_path, parse_error}]}`
- 兩端點皆 read-only，localhost-only（沿用 §2A remote boundary）

### Storage

無新 DB table。結果來自 filesystem + subprocess，每次 call fresh scan（cache in-memory TTL 5 min）。

## UI

- 新增 `ui/tool-discovery.js`，掛在總覽 tab 或新設「Tools」tab
- 每個工具一行：icon + 名稱 + `tool_kind` badge + installed ✓/✗ + version + config source + model
- 全部 read-only，無 edit 按鈕

## Acceptance

1. `GET /tools/discovery` 回傳 registry 中所有 agent 的偵測結果
2. 未安裝工具顯示 `installed: false`，version 為 null
3. `GET /tools/inventory` 回傳 non-secret config 摘要
4. 讀取失敗時回傳 `parse_error` 而非 crash
5. 不讀取任何 API key / token（test 驗證 redaction）
6. UI 顯示 read-only 工具清單，區分 `vibe_coding` / `agentic_runtime`
7. 所有端點 localhost-only
