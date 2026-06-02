# 002 Session Memory Pipeline

Status: Draft
Date: 2026-05-28

> Superseded boundary note (2026-06-02): this spec remains the compatibility contract for
> deterministic summary/review pointer APIs. Formal durable memory compilation is owned by
> session2memory. New agentic-os work must use Session Evidence v1 as the source evidence
> contract.

## Positioning

P1 adds a deterministic Harness Run evidence pipeline on top of the P0 daemon.
It turns completed run output into reviewable, human-approved local knowledge
for the Harness Manager substrate.

It does not add full RAG, embeddings, remote sync, autonomous memory reasoning,
or automatic policy decisions.

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P1 | deterministic session-to-memory pipeline | auditable run evidence and approved local knowledge | summaries, review queue, approved memory | autonomous memory reasoning, embeddings, RAG |

The goal is to make session output reviewable and promotable:

```text
session evidence -> summary/review pointer -> session2memory compiler -> durable memory
```

The pipeline must keep humans in the loop. Raw process logs remain the source of
truth. Memory records are derived artifacts and must cite the source session.
Existing API/CLI labels still use `session`; the product concept is Harness Run
or Harness Session.

## Goals

- Build a session summary from existing session metadata and stdout/stderr JSONL.
- Keep a minimal session state: `last_task`, `last_branch`, `stopped_at`,
  `one_liner`.
- Create a review queue item from a summary.
- Approve or reject review items.
- Promote approved items into a local searchable knowledge base.
- Expose the pipeline through daemon API and `agentctl`.

## Non-Goals

- No LLM summarization in P1.
- No embeddings, vector DB, LanceDB, Redis, or external service.
- No automatic promotion without explicit approval.
- No full repository indexing.
- No Shared Capability Catalog or Harness Launch Policy implementation.

## Data Model

### Session Summary

One summary may exist per session:

```text
id
session_id
agent_id
status
one_liner
last_task
last_branch
stopped_at
stdout_lines
stderr_lines
error_lines
created_at
updated_at
```

The deterministic summarizer uses:

- session metadata from SQLite;
- merged JSONL logs;
- the first useful stdout/stderr line;
- terminal status and exit code.

`one_liner` should be short and factual. If there is no useful log output, it
may fall back to `<agent_id> session <status>`.

### Review Item

Each summary can create at most one active review item:

```text
id
summary_id
session_id
kind
title
body
source
status
created_at
updated_at
```

Allowed statuses:

- `pending`
- `approved`
- `rejected`

P1 only needs one kind: `project_memory`.

### Approved Memory

Approved items become durable memory records:

```text
id
review_item_id
session_id
kind
title
body
source
created_at
updated_at
```

Approved memory is searchable with SQLite FTS when available. A substring
fallback is acceptable only when FTS is unavailable in the local SQLite build.

## API Contract

```http
POST /sessions/{session_id}/memory/summary
GET  /sessions/{session_id}/memory/summary
POST /sessions/{session_id}/memory/review

GET  /memory/review
POST /memory/review/{item_id}/approve
POST /memory/review/{item_id}/reject

GET  /memory
GET  /memory/search?q=<query>
```

Behavior:

- Unknown sessions return `404`.
- Summary creation is idempotent per session.
- Review item creation is idempotent per summary while a non-rejected item
  exists.
- Approving a pending item creates one memory record and marks the item
  `approved`.
- Rejecting a pending item marks the item `rejected` and creates no memory.
- Re-approving or re-rejecting non-pending items returns `409`.
- Search returns approved memories only.

## CLI Contract

```bash
agentctl memory summarize <session_id>
agentctl memory review create <session_id>
agentctl memory review list
agentctl memory approve <item_id>
agentctl memory reject <item_id>
agentctl memory list
agentctl memory search <query>
```

CLI output should stay concise and tab-separated for list commands. Detailed
records may be printed as JSON.

## Storage

P1 adds tables:

```sql
session_summaries(...)
memory_review_items(...)
memories(...)
memories_fts(...)
```

The P0 `sessions`, `events`, and JSONL log contracts must remain backward
compatible. Existing databases must migrate without dropping P0 session data.

## Verification

P1 is complete when:

- unit tests cover summary generation from stdout, stderr, empty logs, and
  failed sessions;
- storage tests cover create, idempotency, approve, reject, and search;
- API tests cover all routes and error mappings;
- CLI tests cover all memory commands;
- P0 regression tests still pass.
