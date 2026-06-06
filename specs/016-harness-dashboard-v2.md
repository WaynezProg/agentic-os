# 014 — Harness Dashboard v2 (P9)

> **Superseded by [`specs/017-harness-dashboard-v2.md`](017-harness-dashboard-v2.md).** Do not implement. Retained for history.

Status: Superseded
Date: 2026-05-30

## Positioning

P9 強化 web UI，成為日常可用的 Harness Manager dashboard。

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P9 | enhanced dashboard UI | daily operator control surface | organized views over daemon APIs, session timeline, approval queue, catalog display | chat UI, IDE integration, agent loop execution, browser driver |

## Tab Structure

| Tab | Content |
|-----|---------|
| **Overview** | 總覽：fleet 健康狀態、running sessions 數量、pending approvals 數量 |
| **Harnesses** | harness instance profiles、health status、config paths、providers |
| **Projects** | 按 project 分組的 surfaces（P6 catalog）和 sessions |
| **Workflow Surfaces** | hooks、skills、commands、subagents、MCP servers 的 catalog view（P6） |
| **Runs** | session 列表、狀態、logs、events |
| **Approvals** | pending/approved/rejected approvals、審核操作（P8） |
| **Memory** | approved memories、review queue（P1 現有） |
| **Audit** | governance events、fleet events、deprecation records（P5/P6 現有） |

## Design Constraints

- **不做 chat UI** — 對話是 harness 的責任
- **不做 IDE** — 編輯是編輯器的責任
- **不做 agent loop** — tool execution 是 harness 的責任
- 保持 no-build：plain HTML + CSS + JS（與 P2 一致）
- 所有資料來自 daemon API，不直接讀檔案

## UI Components

### Session Detail (P7 timeline)
- 按時間排序的 event stream
- log chunks 以可摺疊區塊顯示
- 可過濾 event type
- 每個 event 可展開查看 metadata

### Approval Panel (P8)
- Pending approvals 列表
- Approve / Reject 按鈕
- 審核後 link 到 session

### Workflow Surface View (P6)
- 按 type 分組（hooks、skills、commands、subagents、MCP）
- 標註來源 scope（user/project/local）
- 高亮衝突和覆蓋
- 可搜尋、可過濾

### Harness Health (P4/P5)
- 即時 health status（up/down/unknown）
- Version 和 config fingerprint
- 一鍵觸發 probe

## Out of Scope

- 即時 log streaming（`--follow` 是 CLI 的領域）
- Dashboard authentication 或 multi-user
- 圖表或 analytics（那是外部監控系統）
- 編輯設定檔或 registry

## Compatibility

既有 P2 的 thin UI（index.html + styles.css + app.js）維持存在。P9 可以在同一個 `apps/web/` 目錄下新增頁面或增強現有元件，不破壞既有行為。
