# Duplication Report

Date: 2026-07-17

## Summary

The repository does not need a wholesale rewrite. Eight duplicated concerns are
worth consolidating because they already produce different coverage, safety,
state, or remote behavior.

| Priority | Concern | Current consequence |
|---|---|---|
| P0 | Mutation lifecycle and rollback | File and SQLite changes have incompatible planning, history, conflict, and verification semantics. |
| P0 | Health probing | The same harness can report different health details depending on endpoint. |
| P0 | Native session scanning | Radar and attach discovery disagree on supported tools, identity, bounds, and visibility. |
| P0 | Desktop HTTP transport | Remote mode omits PUT and authenticated SSE cannot use the Keychain token. |
| P1 | Tool/adapter registration | Supported tools are repeated across five modules and already drift. |
| P1 | Launch decision choreography | Launch, retry, approval, and explicit evaluation have semantic drift. |
| P1 | Scope reduction and template resolution | Equivalent merge/diff/template logic has different error handling. |
| P2 | Dashboard/tab data loading | The same sessions, approvals, health, and profile state is fetched repeatedly at different timestamps. |

## 1. Mutation lifecycle and rollback

Classification: accidental duplication around legitimate storage specialization.

Evidence:

- File mutation plan/apply/audit: `src/agentic_os/safe_edit.py:54-143`.
- Standalone file mutation path: `src/agentic_os/safe_edit.py:145-220`.
- File rollback: `src/agentic_os/safe_edit.py:272-295`.
- JSONL backup/history: `src/agentic_os/backup_store.py:27-159`.
- Skill tracked mutation: `src/agentic_os/control_plane.py:285-346`.
- MCP tracked mutation: `src/agentic_os/control_plane.py:586-654`.
- Policy tracked mutation: `src/agentic_os/control_plane.py:896-966`.
- SQLite history/rollback markers: `src/agentic_os/control_plane_history.py:13-150`.

Legitimate divergence:

- File targets require parser/schema/mtime/atomic-replace behavior.
- SQLite entities require domain validation and relational writes.

Accidental divergence:

- patch identity, preview, history envelope, audit coupling, rollback state, and
  verification semantics are separately implemented;
- generic file changes support dry-run and optimistic concurrency, while
  control-plane changes apply directly;
- file history is JSONL while governance history is SQLite;
- no path re-observes effective state after apply or rollback.

Required unification direction:

One storage-neutral change lifecycle with target-specific snapshot/apply/restore
adapters. Storage mechanisms stay specialized; plan/result/history/verification
semantics become one contract.

## 2. Health probing

Classification: accidental execution duplication around legitimate single/batch
presentation differences.

Evidence:

- Synchronous per-harness probe route: `src/agentic_os/api.py:645-666`.
- Synchronous subprocess/result mapping: `src/agentic_os/api.py:3428-3492`.
- Async batch prober: `src/agentic_os/health_prober.py:9-78`.
- Fleet persistence and drift events: `src/agentic_os/fleet.py:72-132`.
- Fleet route group: `src/agentic_os/api.py:2727-2764`.

Legitimate divergence:

- one route needs an immediate diagnostic response;
- fleet probing needs concurrency and persistence.

Accidental divergence:

- command execution, timeout, error mapping, output bounds, and health
  normalization are duplicated;
- immediate probe writes requested/completed events but not `fleet_health`;
- fleet probe adds version/fingerprint but loses immediate probe fields.

Required unification direction:

One probe executor returning a normalized result. Callers choose whether to
persist, batch, or expose detailed output.

## 3. Native session scanning

Classification: accidental scanner duplication around legitimate tool parser and
view specialization.

Evidence:

- Claude scanner: `src/agentic_os/live_sessions.py:173-217`.
- Codex scanner: `src/agentic_os/live_sessions.py:248-303`.
- Fixed radar registry: `src/agentic_os/live_sessions.py:308-335`.
- Transcript readers: `src/agentic_os/live_sessions.py:351-445`.
- Attach JSONL metadata extraction: `src/agentic_os/attach.py:121-143`.
- Registry-root attach traversal: `src/agentic_os/attach.py:146-210`.
- Radar API: `src/agentic_os/api.py:1049-1088`.
- Workspace discovery API: `src/agentic_os/api.py:1319-1344`.

Legitimate divergence:

- Claude and Codex use different store layouts and metadata formats;
- radar, transcript, and bind need different projections.

Accidental divergence:

- root traversal, file bounds, mtime filtering, JSONL head parsing, identity,
  cwd, and timestamp extraction are reimplemented;
- radar is bounded but fixed to Claude/Codex;
- attach is registry-driven but can recursively scan without equivalent time or
  file-count bounds;
- the same native session can be visible in one feature and absent in another.

Required unification direction:

One bounded normalized native-session scanner. Tool adapters own layout/parser
details; radar, transcript, resume, and bind consume normalized records.

## 4. Desktop HTTP transport

Classification: accidental protocol duplication around legitimate Keychain token
injection.

Evidence:

- Web remote bridge selection: `apps/web/api.js:150-176`.
- Web local fetch and method helpers: `apps/web/api.js:174-205`.
- Tauri bridge command: `apps/desktop/src-tauri/src/lib.rs:101-113`.
- Local dispatch: `apps/desktop/src-tauri/src/connection.rs:44-87`.
- Remote dispatch and token injection: `apps/desktop/src-tauri/src/remote.rs:119-203`.
- Daemon PUT support: `src/agentic_os/api.py:353-354`.
- Active-workspace PUT route: `src/agentic_os/api.py:3210-3217`.
- Browser SSE connection: `apps/web/ui/approval-workbench.js:121-143`.
- Authenticated remote SSE route: `src/agentic_os/remote_api.py:96-113`.

Legitimate divergence:

- remote requests must remain in Rust so the bearer token never reaches
  JavaScript;
- local browser fetch does not need authentication.

Accidental divergence:

- Rust manually redefines supported methods and omits PUT;
- response/error semantics are split between browser and Rust transports;
- browser `EventSource` bypasses the Rust bridge and cannot authenticate with
  the Keychain token;
- local profile URL and Rust local-dispatch URL can disagree.

Required unification direction:

One explicit transport contract shared by Web and Tauri, including all supported
HTTP methods and an authenticated stream bridge for remote events.

## 5. Tool and adapter registration

Classification: accidental support-matrix duplication around legitimate
tool-specific parsers.

Evidence:

- Harness registry: `src/agentic_os/registry.py:24-80`.
- Config reader registry: `src/agentic_os/config_inventory.py:29-57`.
- Fixed capability readers: `src/agentic_os/capability_inventory.py:114-268`.
- Agentic runtime selection: `src/agentic_os/agentic_inventory.py:217-225`.
- Fixed native-session scanners: `src/agentic_os/live_sessions.py:308-335`.
- Attach capability matrix: `src/agentic_os/attach.py:72-118`.
- Hard-coded semantic adapter sets: `src/agentic_os/adapter_contract.py:124-146`.

Legitimate divergence:

- each upstream tool needs its own config/session/capability parser.

Accidental divergence:

- supported tool identity, roots, and operation capability are registered in
  several unrelated modules;
- capability coverage includes Gemini but not OpenClaw/Hermes, while other
  inventories use different sets;
- adding a tool requires coordinated edits with no completeness check.

Required unification direction:

One versioned environment-adapter manifest that references specialized readers,
probes, session scanners, and supported actions.

## 6. Launch decision choreography

Classification: accidental orchestration duplication around legitimate source
request construction.

Evidence:

- New launch gate/start/audit: `src/agentic_os/api.py:989-1041`.
- Retry gate/start/audit: `src/agentic_os/api.py:1423-1475`.
- Approval execution recheck/start/audit: `src/agentic_os/api.py:1601-1662`.
- Capacity gate: `src/agentic_os/api.py:366-389`.
- Explicit policy evaluation: `src/agentic_os/api.py:2069-2086`.
- Core evaluation: `src/agentic_os/control_plane.py:1180-1346`.

Legitimate divergence:

- launch, retry, and approval start from different source records.

Accidental divergence:

- capacity, policy, approval/deny, start, and audit sequencing is repeated;
- missing policy is deny in explicit evaluation but open-by-default in launch;
- explicit evaluation is not audited;
- approval recheck has special expiration behavior not represented by a shared
  decision result.

Required unification direction:

One launch-decision service. Entry points supply source context and receive a
single allow/deny/approval result plus durable evidence.

## 7. Scope reduction and template resolution

Classification: accidental duplicated reducers around legitimate parsers and
transport parsing.

Evidence:

- Agentic-os scope merge/diff: `src/agentic_os/config_scope.py:79-193`.
- Harness-native scope merge/diff: `src/agentic_os/harness_config.py:124-273`.
- Template-to-run request during launch: `src/agentic_os/api.py:2842-2862`.
- Template-to-run request during preview: `src/agentic_os/api.py:3250-3274`.

Legitimate divergence:

- agentic-os and upstream files have different path/parser/redaction behavior;
- preview parses query JSON while launch receives a request dictionary.

Accidental divergence:

- winner selection, source attribution, structural diff, explain projection,
  template lookup, message rendering, and request construction are repeated;
- preview maps missing templates to 404 while launch can leak an uncaught
  `KeyError`;
- malformed-scope behavior differs.

Required unification direction:

One scope reducer and one template resolver, each receiving specialized loaders
or transport inputs.

## 8. Dashboard and tab loading

Classification: accidental client orchestration duplication around legitimate
widget rendering.

Evidence:

- Tab dispatch chain: `apps/web/app.js:175-233`.
- Global refresh fan-out: `apps/web/app.js:235-244`.
- Workspace dashboard aggregate: `src/agentic_os/workspaces.py:158-210`.
- Daily dashboard repeated requests: `apps/web/ui/daily-dashboard.js:66-148`.
- Dashboard v2 fan-out: `apps/web/ui/dashboard-v2.js:184-221`.
- Provider switchboard repeated dashboard/session reads:
  `apps/web/ui/provider-switchboard.js:66-110,206-209`.
- Tool discovery loading lifecycle: `apps/web/ui/tool-discovery.js:237-263`.
- Agentic inventory loading lifecycle:
  `apps/web/ui/agentic-inventory.js:82-100`.

Legitimate divergence:

- widgets render different projections and actions.

Accidental divergence:

- tab loading, loading/error states, retry, and page-level data fan-out are
  separately implemented;
- sessions, approvals, profiles, and health can be fetched several times during
  one overview refresh;
- snapshots can represent different moments.

Required unification direction:

A declarative tab-loader map plus a small page-level request deduplicator/cache.
No frontend framework is required.

## Not consolidation targets

The following similarities are intentional or too small to justify an
abstraction:

- tool-specific config/session parsers;
- file versus SQLite low-level snapshot storage;
- local versus remote credential sourcing;
- widget-specific rendering;
- HTML escaping, row mapping, timestamp formatting, and thin CRUD wrappers.

