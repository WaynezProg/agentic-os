# Session Evidence v1 Design

Date: 2026-06-02
Status: Draft for written spec review
Author: agentic-os team
Builds on: `docs/superpowers/specs/2026-05-31-adapter-contract-v2-design.md`
Related specs: `specs/001-daemon-runtime.md`, `specs/002-session-memory-pipeline.md`,
`specs/024-adapter-contract-v1.md`

## Summary

`agentic-os` is a Harness Manager, not an agent runtime and not the durable memory system. Its
responsibility is to launch and observe harness runs, then preserve enough evidence for another
system to understand what happened. Adapter Contract v2 describes what each harness can expose.
Session Evidence v1 makes every run leave a standard evidence bundle on disk.

The core contract is:

```text
this harness run -> standard metadata -> standard event timeline -> artifact manifest -> pointers
```

Formal memory compilation and long-term knowledge promotion move out of `agentic-os`. The owner is
`session2memory`. `agentic-os` keeps only summaries and review pointers that help humans find the
right evidence.

## Locked Scope

- Create a standard per-session evidence bundle under `.agentic-os/sessions/<session_id>/`.
- Emit `metadata.json` for every accepted run, including rejected launch-gate runs.
- Emit `events.jsonl` for every accepted run.
- Emit `artifacts/manifest.json` for every accepted run.
- Expose evidence paths through API and CLI.
- Update product docs so `agentic-os` is positioned as evidence manager, not memory system.
- Keep existing stdout/stderr JSONL logs compatible.
- Keep existing memory endpoints callable for compatibility, but relabel them as summary/review
  pointer surfaces and stop treating them as the formal memory contract.

## Non-goals

- No LLM summarization.
- No embeddings, vector database, or RAG.
- No runtime tool-call proxy.
- No in-harness policy enforcement.
- No deletion of existing SQLite memory tables in this slice.
- No parsing of private harness internals without explicit evidence in stdout, stderr, usage output,
  native config, or adapter contract fields.
- No UI redesign.

## Evidence Directory Layout

Each session directory becomes:

```text
.agentic-os/sessions/<session_id>/
├── session.json
├── metadata.json
├── events.jsonl
├── stdout.jsonl
├── stderr.jsonl
└── artifacts/
    └── manifest.json
```

`stdout.jsonl` and `stderr.jsonl` remain raw process-output logs. `events.jsonl` is the normalized
run timeline. `metadata.json` is the run snapshot. `artifacts/manifest.json` indexes files created
under `artifacts/`.

All paths returned by API/CLI are local filesystem pointers. They are evidence pointers, not remote
URLs and not memory IDs.

## Metadata Contract

`metadata.json` is rewritten at important lifecycle transitions. It is a JSON object:

```json
{
  "schema_version": "session_evidence.v1",
  "session_id": "s_abc123",
  "harness_id": "codex",
  "status": "succeeded",
  "cwd": "/Users/waynetu/bootstrap/agentic-os",
  "argv": ["codex", "exec", "{{message}}"],
  "required_env": ["OPENAI_API_KEY"],
  "pid": 12345,
  "pgid": 12345,
  "exit_code": 0,
  "started_at": "2026-06-02T10:00:00Z",
  "ended_at": "2026-06-02T10:01:00Z",
  "updated_at": "2026-06-02T10:01:00Z",
  "upstream_session_id": "external-123",
  "resolved_profile": "default",
  "resolved_provider": "openai",
  "resolved_model": "gpt-5",
  "adapter_contract_version": "v2",
  "working_tree": {
    "available": true,
    "branch": "codex/session-evidence-v1",
    "head": "abcdef123456",
    "dirty": false,
    "status_summary": {"modified": 0, "untracked": 0}
  },
  "evidence_paths": {
    "metadata": ".agentic-os/sessions/s_abc123/metadata.json",
    "events": ".agentic-os/sessions/s_abc123/events.jsonl",
    "stdout": ".agentic-os/sessions/s_abc123/stdout.jsonl",
    "stderr": ".agentic-os/sessions/s_abc123/stderr.jsonl",
    "artifact_manifest": ".agentic-os/sessions/s_abc123/artifacts/manifest.json",
    "artifact_dir": ".agentic-os/sessions/s_abc123/artifacts"
  }
}
```

Rules:

- `argv` may include command arguments, but `env` values are never written. Only environment variable
  names are allowed.
- `upstream_session_id` mirrors the existing `external_session_id` when discovered.
- `adapter_contract_version` is `v2` when the harness is in `SEMANTIC_HARNESS_IDS`; otherwise it is
  `v1`.
- `working_tree.available` is false when `cwd` is not a git worktree or git inspection fails.
- `working_tree.status_summary` contains counts only. It does not include file contents.
- All evidence paths must be relative to the repo or state directory when possible; absolute paths
  are acceptable when the state directory is outside the project.

## Event Timeline Contract

`events.jsonl` is append-only. Each line is a JSON object:

```json
{
  "ts": "2026-06-02T10:00:00Z",
  "session_id": "s_abc123",
  "harness_id": "codex",
  "event_type": "process_started",
  "severity": "info",
  "message": "process started",
  "metadata": {"pid": 12345, "pgid": 12345}
}
```

Required fields:

- `ts`: UTC ISO timestamp.
- `session_id`: local session id.
- `harness_id`: registry id.
- `event_type`: normalized event name.
- `severity`: one of `debug`, `info`, `warning`, `error`.
- `message`: short human-readable message.
- `metadata`: JSON object. It must not contain secrets.

### Event Types

Session Evidence v1 must emit these lifecycle events when applicable:

| Event type | Emitted when |
|------------|--------------|
| `run_accepted` | daemon accepts a run for launch |
| `session_record_created` | daemon creates a session record for a rejected run |
| `launch_rejected` | launch policy rejects a run before process start |
| `launch_started` | process launch is about to execute |
| `launch_failed` | process creation fails |
| `process_started` | pid and pgid are known |
| `process_exited` | process exits normally or with non-zero code |
| `run_stopping` | stop is requested |
| `run_stopped` | stop finishes |
| `upstream_session_discovered` | native session id is captured |
| `approval_required` | policy creates a human approval item |
| `approval_resolved` | approval is approved or rejected |
| `usage_reported` | usage parser stores usage evidence |
| `upstream_error` | harness output or parser identifies an upstream error |
| `artifact_recorded` | artifact manifest gains an entry |

Reserved event types are valid but not required in the first implementation:

- `model_selected`
- `tool_called`
- `file_changed`
- `config_snapshot_recorded`

Reserved event types must only be emitted when there is explicit evidence. For example,
`model_selected` may be emitted from `resolved_model`; `tool_called` must not be invented from
plain prose.

## Artifact Manifest Contract

`artifacts/manifest.json` exists even when no artifacts are present:

```json
{
  "schema_version": "artifact_manifest.v1",
  "session_id": "s_abc123",
  "artifacts": []
}
```

An artifact entry is:

```json
{
  "id": "art_001",
  "path": ".agentic-os/sessions/s_abc123/artifacts/report.json",
  "kind": "json",
  "media_type": "application/json",
  "size_bytes": 1234,
  "sha256": "hex-digest",
  "source_event_type": "artifact_recorded",
  "created_at": "2026-06-02T10:00:30Z"
}
```

v1 does not need automatic artifact discovery outside `artifacts/`. It only needs the manifest file,
an append/update helper, and stable API/CLI pointers.

## API Contract

Add:

```http
GET /sessions/{session_id}/evidence
GET /sessions/{session_id}/evidence/events
```

`GET /sessions/{session_id}/evidence` returns:

```json
{
  "session_id": "s_abc123",
  "harness_id": "codex",
  "metadata": {
    "schema_version": "session_evidence.v1",
    "session_id": "s_abc123",
    "harness_id": "codex",
    "status": "succeeded",
    "cwd": "/Users/waynetu/bootstrap/agentic-os",
    "adapter_contract_version": "v2",
    "evidence_paths": {
      "metadata": ".agentic-os/sessions/s_abc123/metadata.json",
      "events": ".agentic-os/sessions/s_abc123/events.jsonl",
      "stdout": ".agentic-os/sessions/s_abc123/stdout.jsonl",
      "stderr": ".agentic-os/sessions/s_abc123/stderr.jsonl",
      "artifact_manifest": ".agentic-os/sessions/s_abc123/artifacts/manifest.json",
      "artifact_dir": ".agentic-os/sessions/s_abc123/artifacts"
    }
  },
  "paths": {
    "metadata": ".agentic-os/sessions/s_abc123/metadata.json",
    "events": ".agentic-os/sessions/s_abc123/events.jsonl",
    "stdout": ".agentic-os/sessions/s_abc123/stdout.jsonl",
    "stderr": ".agentic-os/sessions/s_abc123/stderr.jsonl",
    "artifact_manifest": ".agentic-os/sessions/s_abc123/artifacts/manifest.json",
    "artifact_dir": ".agentic-os/sessions/s_abc123/artifacts"
  }
}
```

`GET /sessions/{session_id}/evidence/events` returns:

```json
{
  "events": [
    {
      "ts": "2026-06-02T10:00:00Z",
      "session_id": "s_abc123",
      "harness_id": "codex",
      "event_type": "process_started",
      "severity": "info",
      "message": "process started",
      "metadata": {"pid": 12345, "pgid": 12345},
      "index": 1
    }
  ],
  "truncated": false
}
```

Query parameters for events:

- `after`: default `0`.
- `max_lines`: default `5000`, minimum `1`, maximum `50000`.

Unknown sessions return `404`.

## CLI Contract

Add:

```bash
agentctl sessions evidence <session_id>
agentctl sessions evidence-events <session_id>
```

Behavior:

- `sessions evidence` prints the evidence index as JSON.
- `sessions evidence-events` prints JSONL by default, one normalized event per line.
- `sessions evidence-events --json` prints the API envelope.
- `sessions show <session_id>` may include evidence path fields, but that is additive.

## Memory Boundary

`agentic-os` no longer owns the formal memory system.

In this design:

- `session2memory` is the formal memory compiler and promotion owner.
- `agentic-os` owns local run evidence and pointers to that evidence.
- Existing `/sessions/{id}/memory/summary` remains a compatibility route for a deterministic
  summary pointer.
- Existing `/sessions/{id}/memory/review` remains a compatibility route for review pointers.
- Existing `/memory`, `/memory/search`, and approve/reject routes remain callable in this slice, but
  docs and UI labels must stop presenting them as the canonical memory system.
- No new feature may depend on `agentic-os` approved memories as durable knowledge. New workflows
  must point to `metadata.json`, `events.jsonl`, stdout/stderr logs, and artifact manifest for
  `session2memory` ingestion.

The product language must become:

```text
session evidence -> summary/review pointer -> session2memory compiler -> durable memory
```

not:

```text
session logs -> agentic-os memory -> searchable KB
```

## Data Flow

1. API validates the run request and policy.
2. Supervisor creates a session directory and base evidence files.
3. For an accepted run, evidence writer appends `run_accepted`.
4. For launch-gate rejection, evidence writer appends `session_record_created` then `launch_rejected`,
   writes metadata, and the session becomes failed.
5. For process launch, evidence writer appends `launch_started` and then `process_started`.
6. stdout/stderr continue writing to their existing logs.
7. Process exit updates session status, appends `process_exited`, captures upstream session id when
   available, records usage evidence when parsable, rewrites metadata, and leaves artifact manifest
   in place.
8. API/CLI return pointers to the evidence bundle.
9. `session2memory` consumes the evidence bundle after run completion; `agentic-os` does not promote
   durable memory.

## Error Handling

- Missing `metadata.json`, `events.jsonl`, or `artifacts/manifest.json` on an existing session is
  repairable. The evidence API must recreate empty/missing files from SQLite session state and log
  a warning event.
- Malformed event lines are skipped when reading and do not prevent subsequent valid events from being
  returned.
- Evidence writes must not crash a running harness if the filesystem has a transient write error.
  The supervisor must record a SQLite event and stderr line when possible, then continue the
  process lifecycle.
- Secret redaction must follow existing `control_plane.py` redaction conventions. Environment
  values, tokens, and credential-looking keys are not written to evidence metadata.

## Testing Strategy

Required tests:

- Unit tests for evidence writer file creation, metadata rewrite, event append/read, malformed JSONL
  tolerance, and artifact manifest updates.
- Supervisor tests proving accepted, rejected, succeeded, failed, stopped, and usage-parsed runs
  leave `metadata.json`, `events.jsonl`, and `artifacts/manifest.json`.
- API tests for `/sessions/{id}/evidence` and `/sessions/{id}/evidence/events`.
- CLI tests for `agentctl sessions evidence` and `agentctl sessions evidence-events`.
- Memory-boundary tests proving existing summary/review routes still work while docs/API responses
  identify them as pointers, not formal memory ownership.
- Regression tests proving existing log, session, adapter contract, usage, approval, and memory
  compatibility tests still pass.

Verification command:

```bash
rtk uv run pytest -q && rtk uv run ruff check . && rtk uv run ruff format --check .
```

## Acceptance Criteria

- Every new session directory contains `metadata.json`, `events.jsonl`,
  `artifacts/manifest.json`, `stdout.jsonl`, and `stderr.jsonl`.
- Evidence API and CLI return paths and normalized events for a run without reading private harness
  internals.
- Rejected launches still create evidence bundles.
- Usage parsing emits `usage_reported` when usage evidence is stored.
- `upstream_session_discovered` is emitted when `external_session_id` is captured.
- Product docs state that `agentic-os` manages harness-run evidence and `session2memory` owns formal
  memory compilation.
- Existing v1/v2 adapter contract behavior remains unchanged.

## Future Work

1. Harness Session Model v2: add upstream conversation/thread identity, effective config snapshot,
   and resume strategy as first-class session evidence fields.
2. Runtime Policy Evidence: record preflight config diff warnings and policy decisions as structured
   events before any runtime proxy exists.
3. session2memory Import Adapter: teach `session2memory` to consume `metadata.json`, `events.jsonl`,
   stdout/stderr logs, and `artifacts/manifest.json` directly.
4. UI Evidence View: add a thin evidence tab after the file/API contract is stable.
