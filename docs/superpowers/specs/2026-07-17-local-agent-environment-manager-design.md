# Local Agent Environment Manager Desktop Design

Date: 2026-07-17
Status: Approved

## 1. Product decision

`agentic-os` becomes a **Local Agent Environment Manager** for heterogeneous
agent tools already installed on the operator's Mac.

It is not an agent runtime, model router, workflow builder, package manager, or
cloud control plane. It owns observation, reviewable configuration changes,
session launch/attachment, evidence, and Desktop lifecycle around existing
tools such as Claude Code, Codex, Cursor, OpenCode, OpenClaw, Hermes, Gemini,
and Qwen.

This decision combines:

- Goose-style session and native Desktop usability;
- AgentOS-style separation between runtime and control plane;
- ToolHive/Docker MCP-style capability lifecycle and connection profiles;
- OpenHands-style typed, replayable operational evidence.

No external project is forked. Existing `agentic-os` APIs and mature stores are
preserved.

## 2. Success definition

The app is daily-usable when the operator can:

1. Open the macOS app and see whether the local daemon or configured remote
   connection is healthy.
2. See every supported environment with separate evidence for CLI, config,
   capabilities, runtime, and native sessions.
3. Distinguish installed, configured-only, healthy, degraded, auth-blocked,
   missing, stale, and unsupported states.
4. Preview, approve, apply, verify, and roll back supported configuration or
   capability changes.
5. Launch, resume, attach, stop, retry, and inspect sessions according to each
   adapter's declared support.
6. Review approvals, logs, timelines, evidence, diagnostics, and recent changes
   without navigating a fifteen-item technical menu.
7. Quit and relaunch the packaged app without orphaned listeners or lost state.

## 3. Architecture

### 3.1 Preserved boundaries

- `agentd` remains the only owner of agentic-os-managed harness subprocesses.
- Upstream native sessions remain externally owned.
- Tauri owns Desktop lifecycle, Keychain access, and local/remote transport.
- The Web UI remains a static, no-build, thin API client.
- `SafeEditEngine` remains the only writer for supported external config files.
- Existing `/agents`, `/sessions`, `/skills`, `/mcp`, `/policy`, and config
  endpoints remain compatible.

### 3.2 Built-in Environment Adapter

Add a static, versioned adapter table. Dynamic plugin loading is explicitly out
of scope.

Each `EnvironmentAdapter` declares:

- stable ID, label, and tool kind;
- supported surfaces: CLI, config, Desktop, IDE, background runtime;
- discovery/version/auth/health probes;
- config and capability readers;
- native-session parser and roots;
- launch/resume/attach/stop support;
- restart/reload instructions;
- supported change operations.

Tool-specific parsers remain functions in their existing modules. The adapter
table references them and becomes the only support matrix.

### 3.3 Normalized environment read model

```text
Environment
  id
  label
  tool_kind
  overall_status
  surfaces[]
  config_observations[]
  capabilities[]
  sessions_summary
  health
  pending_change_count
  evidence[]
  observed_at
```

```text
SurfaceObservation
  kind
  status
  source
  version
  path
  detail
  action_required
  evidence
  observed_at
```

Status values:

- `healthy`
- `degraded`
- `missing`
- `configured_only`
- `auth_required`
- `stale`
- `unsupported`
- `unknown`

`overall_status` is a deterministic projection. It never upgrades one surface
from evidence collected for another surface.

### 3.4 Environment APIs

Add:

- `GET /environments`
- `GET /environments/{environment_id}`
- `POST /environments/refresh`
- `POST /environments/{environment_id}/refresh`

Refresh is observation-only. Responses include `observed_at`, bounded errors,
and evidence source paths or probe descriptions without secret values.

Existing discovery and inventory endpoints become compatibility projections
over the Environment service.

### 3.5 Unified health probing

One probe executor owns command execution, timeout, output bounds, duration,
exit code, and error normalization.

The immediate health endpoint returns the detailed result. Fleet probing invokes
the same executor concurrently and persists health/drift state. A probe error for
one environment does not fail the entire refresh.

### 3.6 Unified native-session observation

One bounded scanner service owns:

- configured roots;
- mtime and file-count pruning;
- bounded JSONL head/tail reads;
- normalized identity, workspace, timestamps, title, and log path;
- per-adapter metadata parsing;
- error isolation.

Radar, transcript, workspace discovery, bind, and resume consume the normalized
record. Attach remains a separate action because it starts a different client
process.

## 4. Change lifecycle

### 4.1 Principle

Every supported external mutation follows:

```text
Observe -> Preview -> Approve -> Apply -> Re-observe -> Verify -> Record
```

No mutation is considered successful solely because a file write returned
without error.

### 4.2 Change plan model

```text
ChangePlan
  id
  operation
  environment_id
  target_surfaces[]
  status
  redacted_request
  before_evidence
  diff
  validation
  base_versions
  restart_requirements[]
  backup_ref
  apply_result
  verification
  rollback
  created_at
  updated_at
```

Statuses:

- `previewed`
- `approved`
- `applying`
- `verified`
- `partial`
- `failed`
- `rolled_back`
- `rollback_failed`
- `stale`

### 4.3 Supported operations

The initial discriminated union covers existing product actions:

- MCP copy/remove;
- workflow-surface patch;
- agentic-os config patch;
- harness-native config patch;
- run-profile patch;
- harness-registry patch.

There is no generic mutation language. Existing operation builders continue to
produce `PatchTarget` and `PatchOp`.

### 4.4 Storage and verification

Change plans are stored in the existing SQLite database. Backups remain in the
existing patch directory.

Apply requires the preview's base version to remain current. After apply:

1. re-read the target;
2. parse and validate it;
3. compare the effective value against the planned result;
4. run adapter-declared reload/health verification when supported;
5. record each target surface independently.

Rollback refuses conflicting later edits unless the operator creates a new
explicit rollback plan. Rollback also re-observes and verifies restored state.

Existing direct mutation APIs stay compatible but use the same plan/apply
service internally.

## 5. Launch decisions and sessions

### 5.1 Launch decision

Capacity, policy, approval, and audit sequencing move into one
`LaunchDecisionService`.

Locked compatibility behavior:

- missing policy is explicit open-by-default with a warning;
- the result is audited;
- `/policy/evaluate`, new launch, retry, and approval recheck use the same
  semantics.

### 5.2 Session ownership

- Managed run: full supervisor ownership.
- Native session: observation and resume only.
- Attached session: attach client ownership is surfaced explicitly; no false
  stop/log guarantees are shown.

Environment details expose only actions supported by the adapter and current
session state.

## 6. Desktop connection contract

### 6.1 Local and remote API transport

The Tauri bridge supports GET, POST, PUT, PATCH, and DELETE through one request
and error contract.

Local mode uses the configured local API URL consistently. Remote mode validates
transport, loads the token from Keychain, and injects the bearer header in Rust.
Tokens never enter JavaScript or Desktop TOML.

### 6.2 Remote events

Keep `/events` SSE for native remote clients. Add an authenticated bounded poll
endpoint for the Web Desktop:

- `GET /events/poll?after_id=<id>&limit=<n>`

Remote Web polling goes through the Rust bridge, so it can use the Keychain
token. Polling backs off while disconnected and resumes from the last event ID.

### 6.3 Lifecycle

- Packaged Web assets remain Tauri resources; no production UI server.
- Startup errors are emitted immediately rather than discarded.
- Supervisor owns restart/backoff and connection-state events.
- Quit, crash, and relaunch must converge with no listeners left on managed
  ports.

## 7. Desktop information architecture

Replace fifteen top-level tabs with six areas:

| Area | Primary content | Existing subviews reused |
|---|---|---|
| Home | attention items, active sessions, environment health, recent changes | overview dashboards, approvals summary |
| Environments | normalized environment list and cross-surface detail | tools, agentic inventory, harness health/config |
| Sessions | native and managed sessions, launch/resume/attach, logs/evidence | chat, vibe coding, runs, logs, memory |
| Capabilities | MCP, skills, plugins, hooks, policy | skills/MCP editor, workflow catalog |
| Changes | pending plans, verification, history, rollback, audit | patch history, approvals, audit |
| Settings | connection, workspace, profiles, templates, diagnostics, import/export | existing settings and editors |

There is one navigation model. Existing panels remain internal subviews while
their logic is reused; the old sidebar is removed rather than retained behind a
feature flag.

### 7.1 Environment list

Each row shows:

- environment identity and kind;
- overall status;
- CLI/version proof;
- configured surface count;
- active native/managed sessions;
- pending change count;
- the highest-priority action required.

The detail page shows one card per surface with source, evidence, status, and
supported action. Config residue is visibly different from installed status.

### 7.2 Change center

The Change center shows:

- previewed plans awaiting apply;
- running/partial/failed verification;
- restart/reload requirements;
- verified history;
- rollback availability;
- audit correlation.

Apply is disabled until preview remains fresh. Partial success is never rendered
as globally complete.

### 7.3 Interaction quality

- keyboard-operable navigation and controls;
- visible focus;
- semantic headings and labels;
- responsive layout at 960 px minimum Desktop width and narrow Web widths;
- bounded tables with usable horizontal scrolling;
- explicit loading, empty, degraded, and retry states;
- no emoji-only action labels;
- Traditional Chinese product copy with English technical terms where needed.

## 8. Tauri and release hardening

- Default window: 1280×820.
- Minimum window: 960×640.
- Replace `csp: null` with a restrictive policy that permits packaged assets,
  Tauri IPC, and configured local/remote API connections only.
- Preserve Keychain storage and loopback-only daemon binding.
- Build a release `.app` and DMG.
- Verify launch, quit, crash-orphan cleanup, relaunch, local connection, and
  remote degraded state.

Signing, notarization, and live updater publication are complete only when the
required Apple certificate, notarization credentials, and update endpoint keys
exist and are exercised. Missing credentials are recorded as external blockers,
not hidden behind a passing local build.

## 9. Data migration and compatibility

- Existing SQLite tables and runtime files remain valid.
- New tables use additive migrations.
- Existing API/CLI routes remain operational.
- Existing patch backups and control-plane histories remain readable.
- New navigation reuses old feature modules until each view is migrated.
- No automatic mutation runs during upgrade or first launch.

## 10. Error handling

- One adapter failure returns a degraded environment, not a failed aggregate.
- Secret-bearing values are redacted before storage and response serialization.
- Unparseable config is never treated as an empty writable document.
- Stale change plans return conflict with fresh observation evidence.
- Remote transport errors distinguish unreachable, auth-required, forbidden,
  unsupported operation, and server failure.
- Restart-required is a first-class post-apply state.
- Unsupported adapter actions remain disabled with a reason.

## 11. Verification

Automated gates:

```bash
rtk uv run pytest -q
rtk uv run ruff check .
cd apps/desktop/src-tauri && cargo test
node --check apps/web/app.js
bash scripts/smoke-product.sh
bash scripts/smoke-remote-client.sh
pnpm desktop:build
```

Behavior coverage must prove:

- one adapter definition drives all environment projections;
- CLI/config/runtime evidence remains separate;
- health endpoints share normalized execution semantics;
- radar and bind see the same normalized native session;
- preview/apply/verify/rollback state transitions;
- malformed and stale config refusal;
- remote PUT and authenticated event polling;
- six-area navigation and legacy feature reachability;
- keyboard, loading, empty, error, and narrow-layout behavior;
- packaged app listener cleanup and clean relaunch.

Manual/visual gates:

- screenshots of Home, Environment detail, Sessions, Capabilities, Changes, and
  Settings at 1440×1000 and 960×700;
- packaged app first launch and second launch;
- local daemon failure/retry;
- remote unreachable/auth-required states;
- change preview, verified apply, and verified rollback.

## 12. Non-goals

- Dynamic third-party adapter plugins.
- Agent planning or execution loop.
- Visual workflow builder.
- Cloud synchronization, organizations, or RBAC.
- Package installation resolver.
- Mandatory Docker/Kubernetes.
- Cross-machine native-session synchronization.
- Full transcript search.
- App Store or production auto-update claims without credentials.

## 13. Delivery slices

1. Environment foundation: adapter table, normalized observation, unified probe
   and native sessions.
2. Change foundation: durable plans and verified safe reconciliation.
3. Desktop reliability: transport parity, authenticated events, lifecycle and
   security hardening.
4. Operator UX: six-area navigation, Environment and Change views, reused
   mature subviews.
5. Release proof: complete automated, visual, packaged, and blocker audit.

