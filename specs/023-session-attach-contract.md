# 023 — Session Attach Contract

Status: Implemented
Date: 2026-05-30
Depends on: 018 (`attach_command`), 021 (session model UX)
Optional: yes

## Gate criteria (all required before implementation)

Manual smoke on operator machine after 018–022 merge:

1. Six harness instances run at least once each with captured logs
2. Fleet health records exist for all six ids
3. Surfaces merged view works for all six (empty explicit OK)
4. Harness-native config effective returns for claude + one TOML harness
5. Session timeline shows log_chunk entries
6. Overview / Runs / Approvals pass visual review

If any fail → fix in owning spec, do not start 023.

## Positioning

Define attach semantics for reconnecting operator context to an existing harness
session. Registry stores `attach_command` preview; this spec defines when/how
agentic-os invokes it.

| Phase | Owns | Does not own |
|-------|------|--------------|
| attach | session fields, attach API, harness matrix | PTY UI, full fork/resume matrix |

## Session model extension

Add optional fields to `SessionRecord` (SQLite migration):

| Field | Type | Meaning |
|-------|------|---------|
| `external_session_id` | `str \| null` | Harness-native session id if reported |
| `attachable` | `bool` | Operator may attempt attach |
| `attach_status` | enum | `none`, `available`, `attached`, `unsupported` |

Emit `external_session_id` when harness stdout JSON includes known keys
(openclaw `--json`, future parsers per harness).

## API

```
POST /sessions/{id}/attach
```

Request body: `{ "mode": "preview" | "exec" }`

- `preview` (default): return rendered attach argv, do not spawn
- `exec`: spawn attach_command as subprocess, record audit event, return pid

Response:

```json
{
  "session_id": "s_...",
  "harness_id": "openclaw",
  "attach_command": ["openclaw", "attach", "..."],
  "decision": "allow | deny | unsupported",
  "reason": "..."
}
```

Policy gate: same evaluator as run creation (`approval_required` → 409).

Alternative registry-level attach run:

```
POST /sessions  { "agent_id": "openclaw", "attach_to": "<external_session_id>" }
```

Implement **session-level attach first**; registry-level only if preview mode
insufficient during implementation.

## Harness attach matrix

| harness | support | attach mechanism | notes |
|---------|---------|------------------|-------|
| openclaw | supported | `openclaw attach <id>` | parse id from run JSON |
| hermes | experimental | `hermes --resume <id>` | requires external_session_id |
| opencode | experimental | `opencode attach <url>` | needs server URL from run output |
| claude | unsupported | interactive TUI default | preview only in 023 |
| codex | unsupported | no attach CLI | matrix documents deny |
| qwen | unsupported | resume flags exist but not wired | preview documents future |

## CLI

```bash
agentctl sessions attach <session_id> [--exec]
```

## UI

Runs timeline: "Attach" button when `attach_status == available`. Click →
preview modal with argv; "Run attach" requires confirmation (exec mode).

## Does not own

- Embedded terminal / PTY in browser
- Full resume/fork matrix across all harnesses
- Writing harness session state

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Gate checklist passed | manual sign-off in PR description |
| preview mode returns argv for openclaw session with external id | API test |
| unsupported harness returns `decision: unsupported` | API test |
| exec mode spawns process + audit event | integration test with mock command |
| Policy deny returns 403 with session_id | API test |
| No PTY UI added | file check |

## Implementation plan

`docs/superpowers/plans/2026-05-30-023-session-attach-contract.md`

(Execute only after gate sign-off.)
