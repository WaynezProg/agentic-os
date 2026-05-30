# 017 — Harness Dashboard v2 (P9)

Status: Implemented
Date: 2026-05-30

## Positioning

Enhanced web UI for daily operator use. Plain HTML + CSS + JS, no build step.
All data from daemon API.

| Phase | Owns | Does not own |
|-------|------|--------------|
| P9 | organized views over daemon APIs | chat UI, IDE integration, agent loop execution |

## Tab Structure

| Tab | Status | Content |
|-----|--------|---------|
| Agents | ✅ | Harness instance table with Run form |
| Sessions | ✅ | Session list with actions |
| Logs | ✅ | Log viewer with stream selector |
| Memory | ✅ | Review queue + approved memories + search |
| Skills / MCP | ✅ | Catalog rows + policy summary + evaluation form |
| Fleet | ✅ | Health table, capacity, events, audit trail |
| Harnesses | ✅ | Instance profiles + health check buttons |
| Surfaces | ✅ | Workflow surface catalog with override_by/overrides columns |
| Approvals | ✅ | Approval queue with approve/reject |
| Audit | ✅ | Standalone audit table with domain filter |
| Overview | ✅ | Fleet health, capacity, sessions, approvals summary |

## Implementation Status

### Completed
- 11 tabs in `index.html` (original 6 + 5 new)
- ENDPOINTS extended in `app.js` with harness/catalog/approvals/audit routes
- `loadHarnesses()` / `loadHarnessHealth()` functions
- `loadCatalog()` with override_by/overrides columns rendered
- `loadApprovalsTab()` function with status filter
- `loadAuditStandalone()` with domain filter and limit
- `loadOverview()` showing aggregate health, capacity, sessions, approvals
- Event listeners for catalog-load, approval-load, audit-load buttons
- `test_five_tabs_are_present` updated to check 11 tabs

### Not Doing
- Projects tab (reserved for future)
- Diagnostics tab (reserved for future)
- Chat UI / IDE / agent loop

## Acceptance Criteria & Verification

| Criterion | Status | How to verify |
|-----------|--------|---------------|
| 11 tabs present in HTML | ✅ | `test_five_tabs_are_present` checks 11 tabs |
| Harnesses tab loads instances | ✅ | `loadHarnesses()` in app.js |
| Harness health check works | ✅ | `loadHarnessHealth()` calls API |
| Surfaces tab shows override info | ✅ | override_by/overrides columns rendered |
| Approvals tab loads queue | ✅ | `loadApprovalsTab()` with status filter |
| Audit standalone tab works | ✅ | `loadAuditStandalone()` with domain filter |
| Overview tab shows aggregates | ✅ | `loadOverview()` loads health/capacity/sessions/approvals |
| All tabs refresh on Refresh All | ✅ | `loadHarnesses()` in refreshAll() |
