# P39 Live Session Radar — Design

Date: 2026-06-12
Status: Approved direction (autonomous session; user pre-authorized plan → build → PR)
Branch: `feat/p34-p38-dual-track-product`

## 1. 診斷：為什麼改了 38 個 phase 還是不實用

實測證據（2026-06-12 本機）：

- agentic-os 自己的 sessions DB 只有 **6 筆**（全是 smoke test）；daemon 平常沒在跑。
- 真實的 vibe coding 活動量巨大，但全部發生在 agentic-os 之外：
  - `~/.claude/projects/` 有 **27 個 project 目錄**、上百個 session JSONL。
  - `~/.codex/sessions/` 有 2026/04–06 三個月的 rollout 記錄（來源含 terminal、Codex Desktop、vscode）。
- Dashboard v2（P38）左欄讀的是自家 DB 的 `/sessions` → 永遠顯示 "No sessions yet"。

**根因：launch-first 架構假設。** 整個產品假設使用者會「從 manager 啟動 headless run」（`claude -p "{{message}}"`），資料才會存在。但真實 vibe coding 是 terminal / Cursor / Codex Desktop 的互動式 session — manager 看不到任何真實活動，所以 14 個 tab 管理的是一個空集合。功能愈加愈多，空殼感愈重。

**結論：翻轉成 observe-first。** 直接讀取真實工具已經在寫的 session store，app 一打開就反映今天所有 AI 工具的真實狀態，零工作流遷移成本。這是最快有真實應用價值的路徑。

## 2. 考慮過的方案

| 方案 | 內容 | 評估 |
|------|------|------|
| **A. Observe-first Live Session Radar（採用）** | 後端掃描 `~/.claude/projects` + `~/.codex/sessions`，dashboard 顯示真實 session（active/idle、workspace、標題、resume 指令） | 一天內可交付；打開即有真實資料；建立在 P34/P36/P37 既有讀取模式上 |
| B. Terminal-native launcher | Vibe Coding tab 改成用 osascript 開真實互動 terminal session | 不解決「打開是空的」問題；macOS automation 權限脆弱。降級為 A 之上的一個 action |
| C. 強化 headless run（queue、通知） | 把 `claude -p` 模式做深 | 與 harness 原生功能（Claude Code background task、OpenClaw）直接競爭，違反 README 定位「manager 不是 runtime」。否決 |

## 3. 設計

### 3.1 Backend：`src/agentic_os/live_sessions.py`（新模組，唯讀）

```python
@dataclass(frozen=True)
class LiveSession:
    tool: str                 # "claude" | "codex"
    session_id: str
    workspace: str            # 真實 cwd
    title: str                # session 第一個 user prompt / summary，截 120 字
    started_at: str | None    # ISO8601
    last_activity_at: str     # 檔案 mtime, ISO8601
    active: bool              # now - mtime < 300s
    source: str | None        # codex: originator (vscode/Codex Desktop…)；claude: None
    log_path: str
    resume_command: str       # 可直接貼到 terminal 的一行指令
```

- `scan_claude_sessions(root, *, within_hours, now)`：
  - 走訪 `<root>/<encoded-cwd>/*.jsonl`；**先用 stat mtime 過濾**，過期檔案不開檔。
  - 每檔只讀前 64KB：從 JSONL 行裡取 `cwd`（找不到才 fallback 目錄名解碼）、`sessionId`、started_at。
  - title 優先序：`type:"summary"` 的 summary → queue enqueue 的 content → 第一個 user 訊息文字 → `"(untitled)"`。
  - resume：`cd <ws> && claude --resume <id>`。
- `scan_codex_sessions(root, *, within_hours, now)`：
  - 走訪 `<root>/YYYY/MM/DD/rollout-*.jsonl`，用日期目錄 + mtime 雙重剪枝。
  - 第一行 `session_meta` 給 `id` / `cwd` / `originator`；title 同樣 64KB 內 best-effort。
  - resume：`cd <ws> && codex resume <id>`。
- `scan_live_sessions(claude_root, codex_root, *, within_hours=72, limit=50)`：合併、按 last_activity 降冪、截斷。任一 scanner 例外不可炸掉整個結果（per-tool try/except，回報 `errors` list）。
- **效能邊界**：絕不整檔讀入（現有 P36 discover 的 `read_text()` 全讀是反例）；單檔 IO 上限 64KB；超過 cutoff 的檔案連開都不開。

### 3.2 API：`GET /sessions/live`

- Query：`within_hours`（預設 72，上限 720）、`limit`（預設 50，上限 200）。
- 回應：`{"sessions": [...], "errors": [...], "generated_at": ...}`。
- 唯讀、不過 policy gate（與 `/tools/discovery`、`/agentic/inventory` 同類）。
- 掃描根目錄由 `create_app(..., live_session_roots=...)` 注入，預設 `~/.claude/projects` + `~/.codex/sessions`；測試傳 tmp 路徑。
- 路由放在 `/sessions/{session_id}` 之前註冊（FastAPI 路由順序，避免 `live` 被當成 session_id）。

### 3.3 CLI：`agentctl sessions live`

表格輸出：active 標記、tool、workspace（縮短顯示）、title、last activity、session id。`--within-hours` / `--limit` 透傳。

### 3.4 UI：dashboard-v2 左欄頂部「Live Sessions（真實）」卡片

- 每列：tool badge（claude/codex 配色）、active 綠點或 idle 灰點、workspace basename（title attr 顯示全路徑）、title、相對時間、**[複製 Resume] 按鈕**（`navigator.clipboard.writeText(resume_command)`）。
- 卡片頂部：重新整理按鈕 + 掃描時間。空狀態給出提示文字。
- 既有自家 DB 的 "Recent Sessions" 卡片改名 **"Managed Runs"**，避免與真實 session 混淆。
- `api.js` 新增 `liveSessions` endpoint；`styles.css` 加 badge/dot 樣式。

### 3.5 Open-in-Terminal（stretch，獨立可裁切）

- `POST /sessions/live/open-terminal`，body `{tool, session_id, workspace}`。
- **伺服器端重建指令，不接受 client 傳任意 command**（防注入）：tool 白名單 `{claude, codex}`、session_id 限 `[0-9a-zA-Z-]`、workspace 必須是存在的目錄。
- macOS 用 `osascript -e 'tell application "Terminal" to do script "..."'` + activate；非 darwin 回 501。
- 測試 mock `subprocess.run`，不真開 Terminal。

### 3.6 不做（YAGNI）

- OpenClaw / Hermes / n8n 的 live run 輪詢（P37 inventory 已涵蓋存在性；live 狀態留待後續 phase）。
- Gemini / Qwen / OpenCode scanner（scanner 以 dict 註冊，之後加一個函式即可）。
- 檔案監看 / push 更新 — 進頁載入 + 手動 refresh 就夠。
- 跨機器聚合。

## 4. 測試策略

- `tests/test_live_sessions.py`：tmp 目錄寫 claude/codex 格式 fixture JSONL；驗 parse 欄位、active 判定（`os.utime` 操縱 mtime）、64KB 邊界（大檔只讀頭）、cwd fallback、title 優先序、壞 JSON 不炸。
- `test_api.py`：`/sessions/live` 用 tmp roots；open-terminal 的驗證錯誤（400）與 mocked 成功路徑。
- `test_cli.py`：`sessions live` 渲染。
- `test_web.py`：新 UI 標記存在性斷言（既有模式）。

## 5. 成功標準

1. `uv run pytest -q` 全綠、`uv run ruff check .` 乾淨。
2. 對真實資料驗證：本機啟 daemon，`GET /sessions/live` 回傳今天實際的 Claude/Codex session（含本 session 自己）。
3. Dashboard 打開 = 看到真實活動，按一下就能複製 resume 指令回到任何 session。
