# P6: Governance Closed Loop — Design Spec

## Goal

Close all governance gaps declared in specs/008 (G1–G6). Every state mutation
across skills, MCP servers, policies, sessions, and fleet instances produces a
durable audit event. Deprecated items warn without breaking. Log readers cannot
block the daemon. Policy coverage is queryable.

## Architecture

Single new module `audit.py` owns a unified `audit_events` SQLite table.
Existing session events (storage.py) and fleet events (fleet.py) remain
unchanged — `audit_events` is an additive cross-domain governance trail.
Deprecation is a column-level addition to the existing control_plane.py tables.
Log reader isolation is a bounded-read enhancement to logs.py.

No new daemons, no async rewrites, no event sourcing. All changes are additive
to the existing single-process FastAPI architecture.

## Components

### 1. AuditStore (`src/agentic_os/audit.py`)

New module. Owns `audit_events` table:

```sql
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_domain ON audit_events (domain);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events (entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events (event_type);
```

**domain values**: `skill`, `mcp`, `policy`, `session`, `fleet`, `governance`

**AuditStore class**:
- `__init__(self, db_path: Path)` — stores path, calls no I/O
- `init()` — CREATE TABLE IF NOT EXISTS
- `record(domain: str, entity_id: str, event_type: str, message: str, metadata: dict | None = None)` — INSERT one row
- `list_events(domain: str | None = None, entity_id: str | None = None, event_type: str | None = None, limit: int = 500) -> list[AuditEvent]` — filtered SELECT, ORDER BY id DESC, LIMIT
- `policy_coverage(agent_ids: list[str]) -> list[dict]` — for each agent_id, return `{"agent_id": str, "has_policy": bool, "last_evaluated_at": str | None}`

**AuditEvent dataclass**:
```python
@dataclass(frozen=True)
class AuditEvent:
    id: int
    domain: str
    entity_id: str
    event_type: str
    message: str
    metadata: dict
    created_at: str
```

### 2. CRUD Audit Events (G1 closed loop)

Every skill/MCP/policy mutation in api.py calls `audit_store.record()` after
the control_plane operation succeeds:

| Operation | domain | event_type |
|-----------|--------|------------|
| POST /skills/{id} | skill | skill_upserted |
| POST /skills/{id}/disable | skill | skill_disabled |
| POST /skills/{id}/deprecate | skill | skill_deprecated |
| POST /mcp/{id} | mcp | mcp_upserted |
| POST /mcp/{id}/disable | mcp | mcp_disabled |
| POST /mcp/{id}/deprecate | mcp | mcp_deprecated |
| POST /policy/{agent_id} | policy | policy_upserted |
| POST /policy/{agent_id}/deprecate | policy | policy_deprecated |

metadata contains field-level diffs where applicable (e.g.
`{"field": "enabled", "before": true, "after": false}`). Secret-bearing fields
(env_keys) record key names only, never values — maintaining existing redaction
invariant from control_plane.py.

### 3. Deprecation Lifecycle (G5)

**Schema migration** — ALTER TABLE on each of the three control_plane tables:

```sql
ALTER TABLE skills ADD COLUMN deprecated INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mcp_servers ADD COLUMN deprecated INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_policies ADD COLUMN deprecated INTEGER NOT NULL DEFAULT 0;
```

Migration follows the existing pattern in storage.py (try ALTER, catch
OperationalError if column exists).

**New API endpoints**:
- `POST /skills/{id}/deprecate` — sets deprecated=1, records audit event
- `POST /mcp/{id}/deprecate` — same
- `POST /policy/{agent_id}/deprecate` — same

**ControlPlaneStore changes**:
- `deprecate_skill(skill_id)`, `deprecate_mcp_server(server_id)`, `deprecate_policy(agent_id)` methods
- Existing `list_*` and `get_*` methods return `deprecated: bool` in their records
- `SkillRecord`, `McpServerRecord`, `PolicyRecord` dataclasses gain `deprecated: bool` field

**Policy evaluation warnings**:
- `PolicyEvaluationResult` gains `warnings: list[str]` field (default empty)
- When the evaluated agent's policy is deprecated, add warning
- When a referenced skill or MCP server is deprecated, add warning
- Decision unchanged — deprecated does not mean denied

**CLI display**:
- `agentctl skills list` shows `deprecated` in the status column for deprecated items
- `agentctl mcp list` same
- `agentctl policy show` same

**UI display**:
- Deprecated items show a `deprecated` badge in tables

**Not implemented**:
- No sunset dates, no auto-disable, no un-deprecate endpoint (upsert resets deprecated=0)

### 4. Log Reader Isolation (G2 enforcement)

**logs.py changes**:
- `read_stream()` gains `max_lines: int = 5000` parameter. Stops reading after cap, returns partial.
- `read_merged()` gains same parameter. Applied per-stream before merge.
- Both return a new `ReadResult` dataclass: `entries: list[LogEntry], truncated: bool`

**API changes**:
- `GET /sessions/{id}/logs` response gains `"truncated": bool` field
- When truncated, audit_store records `domain="session", event_type="log_read_truncated"`

**CLI changes**:
- `agentctl logs` prints warning line when truncated: `"(truncated at {max_lines} lines)"`

**Not implemented**:
- No async file I/O rewrite
- No file-level timeout (line cap is more reliable for Python sync I/O)

### 5. Unified Audit Query API

**New API endpoints**:
- `GET /audit/events` — query params: `domain`, `entity_id`, `event_type`, `limit` (default 500)
- `GET /audit/policy-coverage` — returns per-agent policy status and last evaluation timestamp

**Client methods**:
- `audit_events(domain, entity_id, event_type, limit)` → GET /audit/events
- `audit_policy_coverage()` → GET /audit/policy-coverage

**CLI commands** (`agentctl audit` subgroup):
- `agentctl audit events` — flags: `--domain`, `--entity`, `--type`, `--limit`
- `agentctl audit coverage` — tabular output of policy coverage

**UI**:
- Audit Events section added to Fleet tab (below fleet events)
- Shows latest audit events with domain/type/entity filters

### 6. Policy Bypass Verification (G6)

Not a new enforcement mechanism — P3.5/P3.6 already gate `POST /sessions` and
`POST /sessions/{id}/retry`. P6 adds audit verification:

- Every policy evaluation (allow/deny/approval_required) records
  `domain="governance", event_type="policy_evaluated"` with metadata
  `{"agent_id", "decision", "reason"}`
- Every successful session start (queued→running) records
  `domain="governance", event_type="run_started_with_policy"` with metadata
  linking to the policy evaluation

- `GET /audit/policy-coverage` lets operators verify: "every agent that can
  run has a policy, and every recent run has a matching policy_evaluated event"

No auto-remediation — the daemon reports, the operator decides.

## File Changes

| File | Action | Content |
|------|--------|---------|
| `src/agentic_os/audit.py` | Create | AuditStore, AuditEvent, audit_events table |
| `src/agentic_os/control_plane.py` | Modify | deprecated column, deprecate methods, warnings in evaluate |
| `src/agentic_os/api.py` | Modify | audit_store init, CRUD audit hooks, deprecate endpoints, audit query endpoints, policy-coverage |
| `src/agentic_os/logs.py` | Modify | max_lines cap, ReadResult, truncated flag |
| `src/agentic_os/client.py` | Modify | audit_events, deprecate, policy_coverage methods |
| `src/agentic_os/cli.py` | Modify | audit subgroup, deprecate commands, deprecated labels |
| `src/agentic_os/supervisor.py` | Modify | audit event on queued→running transition |
| `apps/web/index.html` | Modify | audit events section, deprecated badges |
| `apps/web/app.js` | Modify | loadAuditEvents, deprecated display |
| `tests/test_audit.py` | Create | AuditStore unit tests |
| `tests/test_control_plane.py` | Modify | deprecated column, deprecate methods, warning tests |
| `tests/test_api.py` | Modify | CRUD audit events, deprecate endpoints, audit query |
| `tests/test_logs.py` | Modify | line cap, truncated flag |
| `tests/test_cli.py` | Modify | audit + deprecate CLI tests |
| `tests/test_web.py` | Modify | audit UI contract tests |

## Governance Principle Coverage

| Principle | P5 status | P6 addition |
|-----------|-----------|-------------|
| G1 Audit-everything | Fleet + session events | CRUD audit events, governance events, log truncation events |
| G2 Failure isolation | Probe timeout | Log reader bounded read |
| G3 Config drift | Drift events | (complete in P5) |
| G4 Capacity bounded | 429 enforcement | (complete in P5) |
| G5 Deprecation | Not started | Deprecated flag + warnings + audit trail |
| G6 No bypass | Launch-time gate | Policy evaluation audit + coverage query |

## Not In Scope

- Multi-user auth, RBAC, tenant isolation
- Cloud sync, remote audit aggregation
- Approval workflow UX (human-in-the-loop)
- Auto-remediation of any governance signal
- Async file I/O or event loop rewrite
- Sunset dates or auto-disable for deprecated items
