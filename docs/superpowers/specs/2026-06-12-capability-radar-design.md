# P40 Capability Radar + P41 Transcript Preview + Desktop Auto-Connect Fix — Design

Date: 2026-06-12
Status: Approved direction (continuation of observe-first pivot; user pre-authorized)
Branch: `feat/p34-p38-dual-track-product`

## 1. 問題

P39 解決了「看不到真實 session」。剩下三個不實用面：

1. **Skill / MCP / plugin / 記憶管理是空的**：P3 control plane 是自家 catalog（要手動登錄），但真實 capability 在各工具自己的 config：`~/.claude/skills`（實測 100 個）、`~/.claude.json` mcpServers（10+）、`~/.codex/config.toml`（17 個 mcp_servers）、`~/.gemini/settings.json`、`~/.qwen/skills`、`~/.config/opencode/{skills,plugins}`、`~/.cursor/mcp.json`。app 一個都看不到。
2. **對話內容看不到**：雷達列出 session 但點不進去；要「管理對話」至少要能預覽每個 session 在講什麼。
3. **Desktop 打開不保證連線**：實測根因 — `ensure_path_dirs` 只保證 `/usr/bin:/bin:/usr/sbin:/sbin`，從 Finder/Dock 啟動時 GUI PATH 沒有 `/opt/homebrew/bin`，dev 模式 `nohup rtk uv run agentd` 直接 command-not-found；supervisor 重試 5 次後 Failed。終端跑同一 script 成功（health ok），證明只差 PATH。`rtk` 在 nohup 下也是純風險（無 agent shell 可壓縮，缺了就整個掛）。

## 2. 方案（同一原則：observe-first，唯讀，名稱不含 secrets）

### P40 `capability_inventory.py` — 真實 capability 盤點

```python
@dataclass(frozen=True)
class MemoryFileInfo:
    path: str          # 宣告路徑（symlink 不解析顯示，但 stat 走 resolve）
    size_bytes: int
    modified_at: str   # ISO8601 UTC

@dataclass(frozen=True)
class ToolCapabilities:
    tool: str          # claude|codex|gemini|qwen|opencode|cursor
    present: bool      # config 目錄存在
    skills: list[str]
    mcp_servers: list[str]   # 只有名稱；永不讀 command/env/url
    plugins: list[str]
    memory_files: list[MemoryFileInfo]
    error: str | None
```

| tool | skills | mcp_servers | plugins | memory |
|------|--------|-------------|---------|--------|
| claude | `~/.claude/skills/*` 目錄名 | `~/.claude.json` 的 `mcpServers` keys | `~/.claude/plugins/cache/*` 目錄名 | `~/.claude/CLAUDE.md` |
| codex | `~/.codex/prompts/*.md` stem | `~/.codex/config.toml` `[mcp_servers.*]` keys（tomllib） | — | `~/.codex/AGENTS.md` |
| gemini | — | `~/.gemini/settings.json` `mcpServers` keys | `~/.gemini/extensions/*` | `~/.gemini/GEMINI.md` |
| qwen | `~/.qwen/skills/*`（含 symlink） | `~/.qwen/settings.json` `mcpServers` keys | — | `~/.qwen/QWEN.md` |
| opencode | `~/.config/opencode/skills/*` | `~/.config/opencode/opencode.json` `mcp` keys | `~/.config/opencode/plugins/*` | `~/.config/opencode/AGENTS.md` |
| cursor | — | `~/.cursor/mcp.json` `mcpServers` keys | — | — |

原則：
- 全部 `home: Path` 注入（測試用 tmp home）；config 一律用 parser（json/tomllib），不用 regex。
- 單檔讀取上限 20MB（`~/.claude.json` 可能很大，超過回 error 不炸）。
- 任一工具讀取失敗 → 該工具 `error` 欄位，不影響其他工具。

API：`GET /tools/capabilities` → `{"tools": [...], "generated_at"}`。`create_app(..., capability_home=None)` 預設 `Path.home()`。
CLI：`agentctl tools capabilities`。
UI：工具 tab 新增「Capabilities（真實）」區：每工具一卡 — skills/MCP/plugins 數量 + 名稱 chips（前 8 個 +N more）、memory 檔案（路徑、大小、mtime）。

### P41 transcript 預覽 — 點進對話

API：`GET /sessions/live/transcript?tool=&log_path=&limit=`
- **安全**：resolve 後的 log_path 必須位於 live session roots（claude/codex 任一）之下且為 `.jsonl`，否則 400 — 防 path traversal 讀任意檔。
- 讀檔尾 256KB（seek，丟掉首個殘行），解析訊息：
  - claude：`type` user/assistant，文字取 `message.content`（string 或 text parts），跳過 `<`/`Caveat:` 開頭與非文字行。
  - codex：`event_msg` 的 `user_message`/`agent_message`、`response_item` 的 message role user/assistant text parts。
- 回 `{"messages": [{role, text≤2000, timestamp}], "count", "truncated"}`，最多 `limit`（預設 50，上限 200）筆，最舊→最新。

UI：雷達卡片列點 title → 列下方展開 transcript 面板（chat 樣式，最後 ~20 則，可關閉）。

### Desktop auto-connect 修正

1. `daemon.rs ensure_path_dirs`：required 加入 `/opt/homebrew/bin`、`/usr/local/bin`（Rust 單元測試覆蓋）。
2. `scripts/desktop-daemon.sh`：daemon 啟動指令去掉 `rtk`（`nohup uv run agentd serve ...`）。
3. 驗證：`cargo test`（src-tauri）過、script 在乾淨 PATH（`env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin`）下 start→health ok。

### 總覽排序

`#dashboard-v2`（含雷達）移到 panel-overview 最頂，工作區儀表板下移 — 打開 app 第一眼是真實活動。

## 3. 不做（YAGNI）

- 寫入任何外部工具 config（install/enable/disable skill、編輯 MCP）— 下一階段再議，本輪純 observe。
- MCP server 的 command/url/env 顯示（secrets 紅線）。
- 記憶檔內容 diff/編輯；只列 metadata。
- Hermes/OpenClaw capability（P37 已有 agentic inventory）。
- Tauri GUI 端到端自動化測試（cargo test + script 乾淨 PATH 實測即可）。

## 4. 測試

- `tests/test_capability_inventory.py`：tmp home 建假 config（每工具最小 fixture）；驗名稱抽取、缺檔 present=false、壞 JSON/TOML → error 欄位、20MB 上限、絕不外洩 value（fixture 內放假 token，斷言不出現在輸出）。
- `test_api.py`：capabilities endpoint（注入 home）；transcript：正常 claude/codex、root 外路徑 400、非 .jsonl 400。
- `test_cli.py`：`tools capabilities` 渲染。
- `test_web.py`：UI 標記 + 總覽排序斷言。
- Rust：`ensure_path_dirs` homebrew 測試。

## 5. 成功標準

1. 全測試綠 + ruff 乾淨 + cargo test 過。
2. 對真實機器：`/tools/capabilities` 列出 claude 100 skills / 10+ MCP、codex 17 MCP…；UI 工具 tab 渲染。
3. 雷達點一列看到該 session 最近對話。
4. `env -i` 乾淨 PATH 模擬 GUI 啟動：desktop-daemon.sh start → health ok。
