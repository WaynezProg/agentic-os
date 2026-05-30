# 016 — Approval Queue (P8)

Status: Implemented with gaps
Date: 2026-05-30

## Positioning

Local operator approval for launch-policy decisions. Approval item created when
policy returns `approval_required`, then approved → session starts, or rejected.

| Phase | Owns | Does not own |
|-------|------|--------------|
| P8 | approval queue, approve/reject lifecycle, audit links | RBAC, notifications, live in-harness tool approval |

## Implementation Status

### Completed
- `GET /approvals` with `?status=`, `?harness_id=`, `?limit=` filtering in `api.py`
- `POST /approvals/{id}/approve` — creates session, links approved_session_id
- `POST /approvals/{id}/reject` — records rejection reason
- `agentctl approvals list --status= --harness= --limit=` in `cli.py`
- `agentctl approvals show/approve/reject` in `cli.py`
- `ApprovalStore` with SQLite persistence (existing)
- 2 API tests for filtering in `test_api.py`
- UI "Approvals" tab in `index.html` + `app.js` loadApprovalsTab()

### Gaps
- **Approved session auto-link in UI** — approved_session_id displayed but not clickable to navigate

### Not Doing
- Multi-user RBAC
- Push notifications
- Auto-approve rules
- Live in-harness tool approval

## Acceptance Criteria & Verification

| Criterion | Status | How to verify |
|-----------|--------|---------------|
| approval_required creates approval item | ✅ | `test_approval_required_run_creates_durable_approval` |
| Pending approval can be approved | ✅ | `test_approvals_list_filter_by_status` |
| Approval creates new session | ✅ | Existing approval test |
| Rejection records reason | ✅ | `test_approval_required_run_can_be_rejected_without_starting_followup_session` |
| Policy change expires pending approval | ✅ | `test_pending_approval_expires_on_read_when_policy_now_denies` |
| Status filtering works | ✅ | `test_approvals_list_filter_by_status` |
| Harness ID filtering works | ✅ | `test_approvals_list_filter_by_harness_id` |
| Limit parameter works | ✅ | Implemented in API |
| Approval audit links visible | ⚠️ | Events recorded, not displayed in approval detail view |
