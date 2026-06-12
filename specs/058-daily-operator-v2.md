# 058 — Daily Operator v2 (P38)

Status: Draft
Date: 2026-06-08
Depends on: `specs/055-vibe-coding-runtime-adapter.md` (P35), `specs/057-agentic-runtime-inventory.md` (P37)

## Scope

| Owns | Does not own |
|------|--------------|
| Dashboard 重新設計為兩欄：Vibe Coding / Agentic Runtime | 新增功能（P34-P37 已做） |
| 聚合 recent workspace、pending approval、failed session、templates | Chat UI |
| 一鍵從 template 啟動 session | RBAC / cloud sync |

## Rationale

P33 已有 daily operator dashboard，但它是單一視圖。P38 把它重構為兩欄佈局，左欄 Vibe Coding（P35 launcher + 最近 sessions），右欄 Agentic Runtime（P37 inventory + attached sessions）。上方保留 workspace/profile/model 狀態列和 quick actions。

## UI Layout

```
┌──────────────────────────────────────────────────────┐
│ Status Bar: workspace | profile | model | provider   │
├──────────────────────────────────────────────────────┤
│ Quick Actions: [switch-profile] [repair] [approve]   │
│                [rollback] [start-template]           │
├──────────────────────────┬───────────────────────────┤
│ Vibe Coding              │ Agentic Runtime           │
│ ┌──────────────────────┐ │ ┌───────────────────────┐ │
│ │ Recent Sessions      │ │ │ Inventory             │ │
│ │ - claude running     │ │ │ - openclaw: 3 skills  │ │
│ │ - codex succeeded    │ │ │ - hermes: 5 tools     │ │
│ │ [Launch New]         │ │ │ [Scan]                │ │
│ └──────────────────────┘ │ └───────────────────────┘ │
│ ┌──────────────────────┐ │ ┌───────────────────────┐ │
│ │ Failed (need retry)  │ │ │ Attached Sessions     │ │
│ │ - claude #42         │ │ │ - openclaw abc123     │ │
│ │ [Retry All]          │ │ │ - hermes xyz789       │ │
│ └──────────────────────┘ │ └───────────────────────┘ │
│ ┌──────────────────────┐ │ ┌───────────────────────┐ │
│ │ Templates            │ │ │ Pending Approvals     │ │
│ │ - daily-coding       │ │ │ - 2 pending           │ │
│ │ [Launch]             │ │ │ [Review]              │ │
│ └──────────────────────┘ │ └───────────────────────┘ │
├──────────────────────────┴───────────────────────────┤
│ Fleet: health | capacity | recent patches            │
└──────────────────────────────────────────────────────┘
```

## Backend

### 新增 API

- `GET /dashboard/v2` → 聚合式 dashboard 資料
  - 回傳：`{status_bar, quick_actions, vibe_coding, agentic_runtime, fleet}`
  - `vibe_coding`: `{recent_sessions: [...], failed_sessions: [...], templates: [...]}`
  - `agentic_runtime`: `{inventory: [...], attached_sessions: [...], pending_approvals: [...]}`
  - 整合 P34-P37 的資料，一次 API call 拿到全部

### 或：前端聚合

另一種做法是不新增後端端點，前端同時呼叫多個現有端點聚合：
- `GET /workspaces/dashboard` — status bar
- `GET /sessions` — recent + failed sessions
- `GET /run-templates` — templates
- `GET /agentic/inventory` — agentic inventory
- `GET /approvals?status=pending` — pending approvals

**建議採用前端聚合**，避免新增後端端點（control-plane 凍結原則）。

## UI 實作

### 修改 `daily-dashboard.js`

- 將現有 `renderDashboard()` 拆為兩欄
- 左欄引用 `VibeCodingLauncher` 的 session list（只讀模式）
- 右欄引用 `AgenticInventory` 和 `SessionAttach` 的 bound sessions
- Quick actions 保留在頂部

### 新增 `ui/dashboard-v2.js`

- 兩欄佈局 CSS
- 左欄：嵌入 vibe-coding-launcher 的精簡版（只有 session list + launch button）
- 右欄：嵌入 agentic-inventory 的精簡版（只有 cards）+ attached sessions
- 上方 status bar 和 quick actions 從現有 `daily-dashboard.js` 抽取

### CSS

```css
.dashboard-v2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
.dashboard-v2 .column {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 1rem;
}
.dashboard-v2 .column h3 {
  margin-top: 0;
}
```

## 與 P33 dashboard 的關係

- P33 dashboard 保留為 `loadOverview()` 的 fallback
- P38 新增 `loadDashboardV2()` 作為預設
- 如果 `GET /dashboard/v2` 不存在，fallback 到 P33 行為
- 長期目標：P33 的 overview tab 被 P38 完全取代

## Acceptance

1. Dashboard 顯示兩欄：Vibe Coding / Agentic Runtime
2. 左欄顯示 recent sessions + failed sessions + templates
3. 右欄顯示 agentic inventory + attached sessions + pending approvals
4. 上方 status bar 顯示 workspace / profile / model / provider
5. Quick actions 按鈕可用（switch-profile, repair, approve, rollback, start-template）
6. 一鍵從 template 啟動 session（跳轉到 Vibe Coding tab 或彈出 launcher）
7. 所有資料來自現有 API（前端聚合，無新後端端點）
8. Responsive：螢幕寬度不足時兩欄變上下排列
9. 不 break 現有 P33 dashboard 功能
