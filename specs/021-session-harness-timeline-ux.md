# 021 — Session & Harness Timeline UX

Status: Implemented
Date: 2026-05-30
Depends on: 015 (timeline API), 018 (per-harness activity)
Parallel with: 020 (no hard dependency — timeline UX does not need harness-native config)
Blocks: 022

## Positioning

Make session timeline the **primary** Runs/Logs view. Correlate harness
activity with session timeline under the same `session_id`. Close 015 gaps
without adding new tabs.

| Phase | Owns | Does not own |
|-------|------|--------------|
| P7+ UX | timeline-first Runs/Logs UI, log_chunk entries, gap closure | live streaming, cross-session analytics |

## Information architecture

### Runs tab (rename from Sessions tab label in UI only — API stays `/sessions`)

Layout (top → bottom):

1. Session list (existing table, compact)
2. Selected session **timeline** panel (primary)
3. Collapsible raw log viewer (secondary — existing stream selector)

### Logs tab

When session selected: show timeline first, logs below. No separate timeline
tab added (017 tab freeze).

### Harness activity link

From timeline entry with `harness_id`, link to filtered harness activity for
same time window (client-side filter, no new API).

## API gap closure (015)

Extend `GET /sessions/{id}/timeline`:

| Entry type | Source | 015 status |
|------------|--------|------------|
| `session_lifecycle` | session status transitions | done |
| `session_event` | events table | done |
| `memory_review` | memory pipeline | done |
| `log_chunk` | stdout/stderr JSONL summaries | **add** — bounded 20 lines per stream |
| `retry_requested` | retry endpoint audit event | **add** — emit on POST retry |
| `approval` | approval store linked to session | **add** — typed entry |

Extend `GET /harnesses/{id}/activity`:

| Gap | Action |
|-----|--------|
| Fleet events missing | Include `health_probe` / `fleet_event` rows where `harness_id` matches |
| No pagination | Add `?limit=` (default 100, max 500) and `?before=` cursor |

## CLI

No new commands. Ensure existing output documents new entry types in `--json`
mode.

## UI components (`apps/web/app.js`)

- `loadSessionTimeline(sessionId)` → renders chronological cards
- `renderTimelineEntry(entry)` — icon + timestamp + summary per type
- `loadLogs()` refactored to require selected session; timeline loads first
- Approvals tab: make `approved_session_id` clickable → selects session + scrolls
  timeline (closes 016 gap)

## test_web.py

- Timeline panel exists when session selected
- `log_chunk` entry type rendered (mock API fixture)
- Runs tab label text updated

## Does not own

- Live log streaming / WebSocket
- Cross-session aggregation dashboard
- New tabs
- Modifying source events

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Timeline shows log_chunk summaries | API test + UI test |
| Retry creates `retry_requested` entry | API test |
| Harness activity includes fleet events | API test |
| Activity pagination with `before` | API test |
| Runs tab timeline is default view | manual + test_web |
| Approval session link navigates to timeline | manual |
| 015 gaps marked closed in spec | spec debt PR |

## Implementation plan

`docs/superpowers/plans/2026-05-30-021-session-harness-timeline-ux.md`
