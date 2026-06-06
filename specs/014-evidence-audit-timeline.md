# 012 — Evidence & Audit Timeline (P7)

> **Superseded by [`specs/015-evidence-audit-timeline.md`](015-evidence-audit-timeline.md).** Do not implement. Retained for history.

Status: Superseded
Date: 2026-05-30

## Positioning

P7 把分散的 sessions、logs、events、memory review 串成一條 timeline，讓每個 harness run 有完整的「案件紀錄」。

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P7 | evidence and audit timeline | chronological view of all events per session/harness | timeline construction, event correlation, per-session history | modifying source events, live event streaming to external systems |

## Motivation

目前 agentic-os 已經有：
- `GET /sessions/{id}` — session metadata
- `GET /sessions/{id}/logs` — stdout/stderr logs
- `GET /sessions/{id}/events` — session events（policy deny 等）
- `GET /audit/events` — 全域 audit events
- `GET /sessions/{id}/memory/summary` — session summary
- `GET /sessions/{id}/memory/review` — review status

但這些是**分散的** API call。P7 提供單一 timeline endpoint。

## Timeline Events

每個 timeline entry：

```text
timestamp:    ISO 8601
type:         session_start | policy_evaluated | process_started | log_chunk |
              session_ended | summary_created | review_created |
              memory_approved | memory_rejected | retry_requested |
              fleet_event | audit_event
source:       session | policy | supervisor | logs | memory | fleet | audit
message:      human-readable description
metadata:     type-specific details
```

Timeline 順序：

1. `session_start` — run requested
2. `policy_evaluated` — policy decision recorded
3. `process_started` / `process_denied` / `approval_required`
4. `log_chunk` — stdout/stderr chunks（可分頁，預設合并顯示）
5. `session_ended` — process exit / stop
6. `summary_created` — deterministic summary generated
7. `review_created` — review queued
8. `memory_approved` / `memory_rejected` — memory pipeline outcome
9. `retry_requested` — retry 觸發，回 step 1

## CLI Commands

```bash
# 顯示單一 session 的完整 timeline
agentctl sessions timeline <session_id>
agentctl sessions timeline <session_id> --type policy_evaluated,session_ended

# 顯示單一 harness instance 的活動歷史
agentctl harnesses activity openclaw@work --since 24h
```

## API Endpoints

```
GET /sessions/{id}/timeline
  ?type=<filter>&limit=<n>&after=<cursor>

GET /harnesses/{id}/activity
  ?since=<duration>&type=<filter>
```

## UI Integration

Dashboard（P9）的 Session Detail view 改為 timeline 格式：
- 按時間排序的 event stream
- 可過濾 event type
- log chunks 以可摺疊區塊顯示
- 每個 event 可展開查看 metadata

## Out of Scope

- 不修改或刪除 source events
- 不做跨 session 的 timeline aggregation（那是 dashboard layer）
- 不做 live streaming（只讀歷史資料）

## Compatibility

既有的 P5/P6 fleet health、governance audit、deprecation lifecycle 維持不變。P7 timeline 是**讀取 view**，不改寫任何既有資料。
