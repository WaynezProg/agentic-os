# 003 Thin UI

Status: Draft
Date: 2026-05-28

## Positioning

P2 adds a browser control panel over the daemon. The UI is thin: it reads state,
shows logs, and calls daemon API endpoints. It must not spawn harness processes,
parse large logs in the UI thread, run indexing, or become an IDE.

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P2 | thin static UI | operator control surface over daemon APIs | status, bounded logs, review UI, catalog placeholders | browser subprocesses, IDE, chat UI |

## Goals

- Provide a local web app under `apps/web/`.
- Show five tabs:
  - Agents
  - Sessions
  - Logs
  - Memory
  - Skills / MCP
- Poll daemon status through HTTP.
- Keep log viewing append-only and bounded.
- Provide memory review and approved-memory views.
- Provide placeholder Shared Capability Catalog views without P3 Harness Launch
  Policy editing. The tab label may remain `Skills / MCP` while the product
  language migrates.

## Non-Goals

- No chat UI.
- No Kanban.
- No code editor.
- No process execution in the UI.
- No embeddings or indexing in the UI.
- No tool approval or model allowlist editor.
- No Electron or Tauri packaging.

## Harness Boundary

The daemon remains the only process owner for Harness Runs. The UI may call:

```text
GET /health
GET /agents
GET /sessions
GET /sessions/{session_id}
GET /sessions/{session_id}/logs
POST /sessions/{session_id}/stop
POST /sessions/{session_id}/retry
POST /sessions/{session_id}/memory/summary
POST /sessions/{session_id}/memory/review
GET /memory/review
POST /memory/review/{item_id}/approve
POST /memory/review/{item_id}/reject
GET /memory
GET /memory/search
GET /skills
GET /mcp
```

The UI must not run shell commands or call `subprocess`.

## UI Layout

The first screen is the usable control panel, not a landing page.

### Agents

- list harness instance id, label, enabled state, cwd mode, stop policy;
- show command preview;
- no harness instance editing in P2.

### Sessions

- list Harness Sessions with id, harness id, cwd, status, exit code, updated
  time;
- actions: view logs, summarize, enqueue review, retry, stop;
- stop/retry errors must be shown as daemon errors, not swallowed.

### Logs

- selected session id input or session picker;
- stream selector: merged, stdout, stderr;
- bounded log view with newest fetched entries appended;
- `after` cursor must come from daemon log indexes.

### Memory

- Provide summary/review pointer views for completed sessions. These views are compatibility
  surfaces; formal durable memory belongs to session2memory.
- review queue list;
- approve/reject actions;
- approved memory list;
- search input using daemon search API.

### Skills / MCP

- placeholder Shared Capability Catalog view for P2;
- shows configured placeholder entries from daemon API;
- no install, no policy, no permissions editor.

## API Additions

P2 adds local-only read endpoints:

```http
GET /skills
GET /mcp
```

Response shape:

```json
{"skills":[{"id":"...", "label":"...", "status":"placeholder"}]}
{"servers":[{"id":"...", "label":"...", "status":"placeholder"}]}
```

The daemon should allow local browser development origins so the static dev
server can call the API. This is for local single-user development only.

## Development Server

P2 uses a no-build static web app to avoid adding Node dependencies in this
phase.

Start the UI:

```bash
cd apps/web
python -m http.server 5173
```

Then open:

```text
http://127.0.0.1:5173
```

The default daemon API is:

```text
http://127.0.0.1:8767
```

The UI must allow overriding this value.

## Verification

P2 is complete when:

- static files exist under `apps/web/`;
- tests verify required tabs and daemon endpoint usage;
- browser smoke verifies the UI loads from the dev server and can reach a
  running daemon;
- P0/P1 tests still pass.
