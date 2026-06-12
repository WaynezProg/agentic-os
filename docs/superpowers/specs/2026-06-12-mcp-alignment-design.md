# P42 MCP Alignment — Design

Date: 2026-06-12
Status: Approved direction (continuation; user asked to design the next phase after P40/P41 observe-only round)
Branch: `feat/p34-p38-dual-track-product`

## 1. 問題

P40 讓六個工具的 MCP server **看得到**（claude 12、codex 14、gemini 11、qwen 12、opencode 12、cursor 14），但工具間明顯 drift，而使用者的明確目標是「Cursor、Codex、Claude、Gemini、Qwen、OpenCode 維持同一套行為」。現在對齊要手動改六份格式不同的 config。這是本專案第一個「寫入」動作的正確切入點：**把某工具已有的 MCP server 複製到另一個工具 / 從某工具移除**，不發明新東西，只搬使用者已經驗證過的設定。

實測前置事實：
- P10 `SafeEditEngine` 已有完整 dry-run / diff / schema 驗證 / backup snapshot / audit / `base_mtime` 衝突偵測 / rollback；`tomli-w` 已在依賴中。
- `schema_registry` 已白名單 claude/cursor/codex/opencode/qwen 的 mcp path，schema 檔已存在 — 但 **gemini 缺席**、**opencode 白名單錯**（寫 `mcpServers`，真實檔案用 `mcp` key、command 是陣列）。
- P10 的 `resolve_write_path` 指向 settings 檔，**與真實 MCP 位置不符**（claude 的 MCP 在 `~/.claude.json` 不在 `~/.claude/settings.json`）— 所以 P42 自帶路徑表（與 P40 capability_inventory 同源），直接組 `PatchTarget` 餵 `SafeEditEngine`，不動 P10 既有行為。
- 本機 `~/.codex/config.toml` 無註解 → tomli-w round-trip 無損（一般情況下註解會丟失，文件中標示）。
- opencode 真實 config 的 args 內含 API key → **任何 API 回應都不得包含 server 定義的 values**，只回 key 名稱。

## 2. 方案比較

| 方案 | 內容 | 評估 |
|------|------|------|
| **A. Copy-from-existing + remove（採用）** | 只支援「從已有該 server 的工具複製到另一個工具」與「移除」；server 定義在後端檔案間搬移，永不經過 UI | 不用設計新增表單、secrets 不過網路層、覆蓋對齊主場景 |
| B. 完整 MCP server CRUD 編輯器 | UI 表單編輯 command/env/url | secrets 會流經 UI 與 API；表單要處理六種 schema；scope 爆炸。否決 |
| C. 一鍵全量同步（以某工具為 source of truth） | 整組 mcpServers 對齊 | 破壞性大、各工具本來就該有差異（如 cursor 專屬）。先做單 server 粒度，全量留作後續 |

## 3. 設計

### 3.1 `src/agentic_os/mcp_alignment.py`（新模組）

路徑表（單一事實來源，供 read/write 共用）：

| tool | file | root key | format |
|------|------|----------|--------|
| claude | `~/.claude.json` | `mcpServers` | json |
| cursor | `~/.cursor/mcp.json` | `mcpServers` | json |
| gemini | `~/.gemini/settings.json` | `mcpServers` | json |
| qwen | `~/.qwen/settings.json` | `mcpServers` | json |
| opencode | `~/.config/opencode/opencode.json` | `mcp` | json |
| codex | `~/.codex/config.toml` | `mcp_servers` | toml |

Canonical 中介格式（內部用，不出 API）：

```python
@dataclass(frozen=True)
class CanonicalServer:
    transport: str            # "stdio" | "remote"
    command: str | None       # stdio
    args: list[str]
    env: dict[str, str]
    url: str | None           # remote
    extras: dict[str, object] # 不認得的欄位原樣保留（headers 等）
```

轉換 adapter：
- claude/cursor/gemini/qwen/codex：`{command, args, env, url}` 直接對映；有 `url` 無 `command` → remote。
- opencode：`type: "local"` ↔ stdio，`command: [bin, *args]` ↔ command+args，`environment` ↔ env，`type: "remote"`+`url` ↔ remote；寫入時補 `enabled: true`。
- `to_canonical(tool, raw)` 失敗（缺 command 且缺 url）→ `ValueError("unsupported server shape")`。
- `extras` 保留來源工具不認得欄位，但**只在同 schema 家族間帶過去**（mcpServers 家族互傳帶 extras；進出 opencode/codex 只帶 canonical 欄位）。

核心函式：
```python
read_server_names(tool, home) -> list[str]               # matrix 用（名稱）
read_server_def(tool, name, home) -> dict | None          # 內部，含 values
build_copy_patch(from_tool, to_tool, name, home) -> tuple[PatchTarget, list[PatchOp], dict]
build_remove_patch(tool, name, home) -> tuple[PatchTarget, list[PatchOp], dict]
summarize_def(raw) -> dict   # keys-only：{"fields": ["command","args(3)","env:TOKEN,API_KEY"], "transport": "stdio"}
```
- `PatchTarget(harness_id=tool, kind="mcp_server", target_kind="capability_mcp", scope="user", file_path=路徑表, file_format=...)`。
- copy 的 op：`PatchOp(op="set", path=f"{root}.{name}", value=translated)`；remove：`op="remove"`（以 patch_engine 實際支援的 op 名為準）。
- `summarize_def` 是唯一可進 API 回應的形狀：欄位名與 env key 名，**永無 values**。

### 3.2 Schema registry 修正

- 新增 `schemas/gemini/mcp_server@v1.json`（同 claude 形狀）+ 白名單 `("gemini", "mcp_server"): ("mcpServers",)`。
- opencode 白名單改為 `("opencode", "mcp_server"): ("mcpServers", "mcp")`（保留舊 prefix 不破壞既有測試），schema 補上 `mcp` key 的真實形狀（type/command array/enabled）。

### 3.3 API（全部 `capability_home` 注入，與 P40 同參數）

- `GET /tools/mcp/matrix` → `{"servers": [{"name", "tools": {tool: bool}}], "tools": [...], "generated_at"}`。名稱聯集、按出現工具數降冪。
- `POST /tools/mcp/copy` body `{server, from_tool, to_tool, dry_run=true}`：
  - 404 source 無此 server；409 target 已有；400 不支援的形狀／工具名。
  - 經 `SafeEditEngine.apply(..., source="mcp_alignment", dry_run=dry_run)`。
  - 回應：`{server, from_tool, to_tool, applied, patch_id, summary: summarize_def(...), validation, backup_path}` — **無 diff 原文，無 values**。
- `POST /tools/mcp/remove` body `{tool, server, dry_run=true}`：404 無此 server；其餘同上。
- 寫入走 daemon 行程 — 與「單一寫者」原則一致；backup/rollback/audit 自動掛上 P10 既有鏈（patches CLI/UI 可回滾）。

### 3.4 CLI

```
agentctl tools mcp-matrix
agentctl tools mcp-copy --server context7 --from claude --to gemini [--apply]
agentctl tools mcp-remove --tool gemini --server context7 [--apply]
```
**預設 dry-run**，`--apply` 才真寫 — 與使用者「敢說真話、防呆」風格一致。

### 3.5 UI（工具 tab，Capabilities 區下方）

- 「MCP 對齊矩陣」：列 = server 名稱（聯集），欄 = 六工具；✓ / ✗，drift（非全有非全無）列高亮。
- ✗ 格 hover → 「複製自…」（來源若多個，下拉選）；✓ 格 → 「移除」。
- 兩段式：先打 dry-run → modal 顯示 keys-only summary + backup 路徑 + **active session 警告**（查 `/sessions/live`，目標工具有 active session 時提示「該工具執行中，設定可能被它自己覆寫」）→ 確認才 `dry_run=false`。
- 完成後重刷 matrix + capabilities 卡片。

### 3.6 不做（YAGNI）

- 新建 MCP server 表單、編輯既有 server 欄位（只搬移與移除）。
- skills / plugins 的寫入（symlink/安裝器另一個世界）。
- 全量一鍵同步、專案 scope（只動 user scope）、enable/disable 切換。
- openclaw / hermes 寫入（agentic runtime 另有 config 慣例）。

## 4. 測試

- `tests/test_mcp_alignment.py`：六工具 to/from canonical 往返、opencode 陣列 command 雙向、extras 保留規則、summarize_def 永無 values（fixture 塞假 token 斷言不出現）、copy/remove ops 形狀。
- `test_api.py`：matrix；copy dry-run（檔案不變）；copy apply（目標檔多出 server、來源檔不變、backup 存在）；409/404/400；TOML 目標（codex）round-trip 後 `tomllib` 可重讀；回應全文不含 fixture 假 secret。
- `test_cli.py`：三個指令；`--apply` 與預設 dry-run 行為。
- `test_web.py`：matrix 標記、modal 標記。
- 既有 schema/safe-edit 測試保持綠（opencode 白名單為「新增」prefix）。

## 5. 成功標準

1. 全測試綠 + ruff + 既有 P10 測試不破。
2. fixture home 端到端：copy claude→gemini → gemini settings.json 出現 server 且 parse 有效 → rollback 還原。
3. 真實機器只跑 **dry-run** 驗證（不動使用者真 config），UI matrix 用真資料渲染、drift 高亮正確。
4. API 回應與 UI 永不出現 command/env/url values（自動化斷言）。
