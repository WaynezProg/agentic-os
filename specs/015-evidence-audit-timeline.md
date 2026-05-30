# 015 — Evidence & Audit Timeline (P7)

Status: Implemented
Date: 2026-05-30

## Positioning

Correlates sessions, logs, events, memory review into chronological timeline.
Read-only view — does NOT modify source events.

| Phase | Owns | Does not own |
|-------|------|--------------|
| P7 | timeline construction, event correlation, per-session history | modifying source events, live streaming |

## Implementation Status

### Completed
- `GET /sessions/{id}/timeline` in `api.py` — correlates session lifecycle, events, memory review
- `GET /harnesses/{id}/activity` in `api.py` — per-harness session event timeline
- Type filtering (`?event_type=`) applies to lifecycle, events, and memory entries
- `agentctl sessions timeline --type` CLI command
- `agentctl harnesses activity --type` CLI command
- `_timeline_entry()` helper function
- 2 API tests in `test_api.py`

### Gaps (closed in 021)
- **Log summaries in timeline** — ✅ `log_chunk` via `logs.read_tail` — `test_session_timeline_includes_log_chunks`
- **Fleet events correlation** — ✅ merged in harness activity — `test_harness_activity_includes_fleet_events`
- **Retry events** — ✅ `retry_requested` on retry — `test_session_timeline_includes_retry_requested`
- **Pagination** — ✅ `limit` / `before` query params — `test_harness_activity_pagination`
- **UI integration** — ✅ Runs tab `#session-timeline` — `test_session_timeline_panel_exists`

### Not Doing
- Live streaming
- Cross-session aggregation
- Modifying or deleting source events

## Acceptance Criteria & Verification

| Criterion | Status | How to verify |
|-----------|--------|---------------|
| Session start/end events in timeline | ✅ | `test_session_timeline_returns_entries` |
| Session events (policy decisions) in timeline | ✅ | Included in timeline entries |
| Memory review events in timeline | ✅ | summary_created, review_pending entries |
| 404 for unknown session | ✅ | `test_session_timeline_404` |
| Harness activity returns session events | ✅ | `test_harness_activity_returns_sessions` |
| Harness activity 404 | ✅ | `test_harness_activity_404` |
| Type filtering on timeline entries | ✅ | Applied to lifecycle + events + memory |
| CLI `sessions timeline --type` | ✅ | Implemented |
| CLI `harnesses activity --type` | ✅ | Implemented |
| Client `harness_activity(event_type=...)` | ✅ | Implemented |
| Approval events correlated | ⚠️ | Via session events, not explicit typed entries |
| Log summaries in timeline | ❌ | Not implemented |
| Fleet events in harness activity | ❌ | Not implemented |
| Pagination (limit/after) | ❌ | Not implemented |
