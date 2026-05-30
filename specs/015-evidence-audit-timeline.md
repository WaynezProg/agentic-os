# 015 — Evidence & Audit Timeline (P7)

Status: Implemented with gaps
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

### Gaps
- **Log summaries in timeline** — spec says "log_chunk" entries should appear, but currently only session lifecycle events are included
- **Fleet events correlation** — harness activity shows session events but does NOT include health_probe/fleet_event entries
- **Retry events** — spec lists "retry_requested" but no explicit retry event in timeline
- **No pagination** — harness activity always returns [:100] with no offset/before/after
- **No UI integration** — timeline/activity not displayed in web UI

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
