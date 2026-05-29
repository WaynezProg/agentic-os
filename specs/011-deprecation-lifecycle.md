# 011 -- Deprecation Lifecycle Completion (P9)

Status: Planned
Date: 2026-05-29

## Positioning

P6 added a boolean `deprecated` flag and warnings. P9 completes that lifecycle
without turning the Harness Manager into a package manager. Operators can set a
reason, replacement, and sunset date; undo deprecation; and let expired
deprecations auto-disable during normal daemon operations.

This is governance metadata and deterministic state transition logic only.

## Goals

1. **Structured deprecation metadata** -- skills, MCP servers, and policies store
   `deprecated_at`, `deprecation_reason`, `replacement_id`, and `sunset_at`.

2. **Undo path** -- operators can un-deprecate records without doing a full
   upsert.

3. **Sunset enforcement** -- when `sunset_at <= now`, the daemon disables the
   deprecated record and records an audit event. Enforcement is opportunistic on
   read/evaluate/mutate, not a background scheduler.

4. **Operator visibility** -- CLI and UI show reason, replacement, and sunset
   date for deprecated records.

5. **Audit completeness** -- deprecate, un-deprecate, and auto-disable events
   include before/after metadata.

## Data Model

Add nullable columns to `skills`, `mcp_servers`, and `agent_policies`:

```sql
deprecated_at TEXT;
deprecation_reason TEXT NOT NULL DEFAULT '';
replacement_id TEXT;
sunset_at TEXT;
```

Existing `deprecated INTEGER NOT NULL DEFAULT 0` remains the fast status flag.

## API Contract

Existing deprecate endpoints accept optional JSON body:

```json
{
  "reason": "superseded by reviewer-v2",
  "replacement_id": "reviewer-v2",
  "sunset_at": "2026-06-30T00:00:00Z"
}
```

New endpoints:

- `POST /skills/{id}/undeprecate`
- `POST /mcp/{id}/undeprecate`
- `POST /policy/{agent_id}/undeprecate`

List/show responses include the new metadata fields.

## Sunset Enforcement

The daemon runs an opportunistic check before:

- listing/showing skills, MCP servers, or policies;
- evaluating policy;
- upserting, disabling, deprecating, or un-deprecating records.

If a record is `deprecated=true`, `enabled=true`, and `sunset_at <= now`, the
daemon sets `enabled=false`, keeps `deprecated=true`, and records:

- `skill_auto_disabled_after_sunset`
- `mcp_auto_disabled_after_sunset`
- `policy_auto_disabled_after_sunset`

This avoids a scheduler while still ensuring stale deprecated capabilities do
not remain silently active after their sunset.

## CLI and UI

CLI:

```bash
agentctl skills deprecate reviewer --reason "use reviewer-v2" --replacement reviewer-v2 --sunset 2026-06-30T00:00:00Z
agentctl skills undeprecate reviewer
agentctl mcp deprecate filesystem --reason "unsafe transport"
agentctl policy deprecate shell --sunset 2026-06-30T00:00:00Z
```

UI:

- Show deprecation reason, replacement, and sunset in Skills / MCP and Policy
  summary tables.
- Add no modal workflow; use the existing thin table-oriented UI pattern.

## Non-Goals

- No delete/purge endpoint.
- No package installation, upgrade, or dependency resolver.
- No background scheduler.
- No remote policy sync.
