# 013 — Approval Queue (P8)

Status: Draft
Date: 2026-05-30

## Positioning

P8 把現有的 `approval_required`（目前只是 failed session）變成真正的 pending → approve → start workflow，讓 operator 可以在 CLI 或 UI 中審核 launch policy 決策。

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P8 | approval workflow | local operator approval for launch-policy decisions | approval queue, approve/reject lifecycle, audit links to sessions | RBAC, notifications, live in-harness tool approval |

## Current State

目前 P7 已經實作了 approval 的基礎設施：
- `POST /approvals/{id}/approve` — 創建 session 並啟動
- `POST /approvals/{id}/reject` — 拒絕並記錄
- `GET /approvals` / `GET /approvals/{id}` — 查詢
- `ApprovalStore` — SQLite 儲存
- `agentctl approvals list/show/approve/reject` — CLI

P8 的改進是把 approval 從 "failed session 的附帶效果" 變成 **一級公民**，有獨立的 queue view 和 lifecycle。

## CLI Commands (Existing, Enhanced)

```bash
# 列出所有 pending approvals
agentctl approvals list
agentctl approvals list --harness openclaw@work
agentctl approvals list --status pending

# 顯示單一 approval 的詳細資訊
agentctl approvals show <id>

# 審核
agentctl approvals approve <id>
agentctl approvals reject <id> --reason "不符合 policy"
```

## API Endpoints (Existing, Enhanced)

既有 `/approvals` 端點已存在。P8 新增：

```
GET /approvals
  ?status=pending|approved|rejected|expired
  &harness_id=<id>
  &limit=<n>
```

回應包含 `approval_id`、`source_session_id`、`approved_session_id`（approve 後）、`harness_id`、`reason`、`status`。

## Lifecycle

```
approval_required (policy decision)
  → create approval item → status: pending
    → approve → status: approved → start session → link approved_session_id
    → reject → status: rejected → record rejection reason
    → policy changes → status: expired → record expiration reason
```

每個 transition 記錄 audit event。

## UI Integration

Dashboard（P9）的 Approvals tab：
- Pending approvals 列表（按時間排序）
- 每個 approval 顯示 harness、cwd、reason
- Approve / Reject 按鈕
- 審核後 link 到對應的 session

## Out of Scope

- Multi-user RBAC
- Push notifications（email、webhook 等）
- Live in-harness tool approval（那是 harness 內部的責任）
- Auto-approve based on rules

## Compatibility

既有的 approval API 和 ApprovalStore 完全保留。P8 是**workflow 完善化**，不破壞現有行為。
