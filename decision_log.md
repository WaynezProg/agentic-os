# Decision Log

This file is append-only.

## 2026-07-17 — Adopt Local Agent Environment Manager architecture

### Purpose

Turn the existing Harness Manager substrate into a daily-usable macOS Desktop
app for observing and safely managing heterogeneous local agent environments.

### Decision and rationale

- Keep `agentic-os` as a control plane, not an agent runtime.
- Preserve the daemon, stores, supervisor, safe-edit engine, remote security,
  and Tauri shell.
- Add a static built-in Environment Adapter table as the single support matrix.
- Separate observed state from reviewable change plans.
- Require post-apply and post-rollback re-observation before marking changes
  verified.
- Replace fifteen top-level technical tabs with Home, Environments, Sessions,
  Capabilities, Changes, and Settings.
- Keep the no-build Web client and reuse existing feature panels as subviews.

This approach preserves the mature backend and test suite while correcting the
current product-model and navigation fragmentation.

### Alternatives considered

- Desktop-only redesign: rejected because it would preserve duplicated health,
  discovery, session, mutation, and remote-transport semantics.
- Fork Goose, ToolHive, Open WebUI, or another Agent OS: rejected because their
  runtime/chat/workflow ownership does not match this control-plane product.
- Build a full agent runtime or visual workflow system: rejected as outside the
  stated environment-management goal.
- Dynamic adapter plugins: rejected until a real external adapter requirement
  exists; built-in static adapters are simpler and verifiable.

### Verification

- Primary-source research:
  `docs/research/2026-07-17-agent-os-desktop-reference.md`.
- Current-state flow and duplication evidence:
  `PATHFINDER-2026-07-17/`.
- Approved design:
  `docs/superpowers/specs/2026-07-17-local-agent-environment-manager-design.md`.

### Re-evaluation conditions

Revisit the boundary only if the product must execute its own agent loop,
support third-party runtime-loaded adapters, provide organization/cloud control,
or author visual multi-agent workflows.

## 2026-07-17 — Implement the Environment foundation

### Purpose

Replace duplicated tool discovery, health probing, native-session scanning, and
launch checks with one normalized environment substrate while preserving every
existing API contract.

### Decision and rationale

- Add one static adapter table for Claude, Codex, Cursor, Hermes, OpenClaw,
  OpenCode, and Qwen, keyed by `SEMANTIC_HARNESS_IDS`.
- Keep CLI, config, capability, runtime, Desktop, and IDE observations
  independent so one healthy surface never proves another.
- Route fleet health and direct health checks through `ProbeService`.
- Route live-session radar, discovery, transcript lookup, and bind through
  `NativeSessionService` with bounded file scanning.
- Route new launch, retry, approval execution, and explicit policy evaluation
  through `LaunchDecisionService`.
- Preserve the established safety distinction: ordinary launch is open with a
  warning when no policy exists, while explicit evaluation and approval
  revalidation require a policy and deny when it is missing.
- Keep `/tools/discovery`, `/tools/inventory`, `/tools/capabilities`, and
  `/agentic/inventory` as compatibility projections of the normalized service.

### Verification

- `rtk uv run pytest -q` — 824 passed.
- `rtk uv run ruff check .` — passed.
- Compatibility tests retain the existing endpoint keys and status codes, and
  adapter coverage is asserted against `SEMANTIC_HARNESS_IDS`.

## 2026-07-17 — Add durable verified Changes

### Purpose

Make every supported external config mutation reviewable, stale-safe,
post-verified, and rollback-verifiable without replacing the existing
`SafeEditEngine` writer or breaking legacy API clients.

### Decision and rationale

- Add the additive `change_plans` SQLite table with `id`, `operation`,
  `environment_id`, `status`, validated `payload_json`, `created_at`, and
  `updated_at`.
- Support explicit operations only: `mcp.copy`, `mcp.remove`, `catalog.patch`,
  `config.patch`, `harness_config.patch`, `profile.patch`, and
  `registry.patch`.
- Persist only identifiers, structural patch paths, hashes, timestamps,
  validation, and verification in plans. Raw command, URL, env, config, profile,
  and registry values never enter the plan or API response.
- Keep restart-durable raw preview payloads under
  `.agentic-os/change-payloads/` with directory mode `0700` and file mode
  `0600`; delete each payload after apply, stale rejection, or terminal failure.
  This is inside the same local trust boundary as the target config and existing
  P10 backups.
- Reject malformed JSON/TOML before preview or apply. A preview becomes `stale`
  if target hash/mtime changes; MCP copy also tracks the source config hash and
  mtime.
- After apply, re-read the target and compare the parsed document or standalone
  content hash to the expected result. After rollback, require the original
  existence/hash/mtime evidence to match.
- Refuse rollback when the applied target changed afterward, preventing a
  rollback from clobbering newer edits.
- Keep each catalog semantic op as one Change plan; a legacy batch request is
  projected as multiple explicit plans.
- Route legacy MCP, catalog, agentic config, harness config, profile, and
  registry endpoints through `ChangeService`. They retain legacy fields and add
  `change_id`, `status`, and `verification`; historical P10 patch rollback
  remains available as fallback.

### Alternatives considered

- Store full patch values in SQLite: rejected because plan history and API
  serialization would create a second durable secret store.
- Keep pending values only in process memory: rejected because Desktop restart
  would make approved previews impossible to apply.
- Add a generic mutation registry or reflection-based DSL: rejected because
  explicit operation builders are easier to audit and preserve owner-module
  validation.
- Roll back without checking post-apply drift: rejected because it can silently
  overwrite a newer operator edit.

### Verification

- `rtk uv run pytest -q` — 847 passed.
- `rtk uv run ruff check .` — passed.
- Focused API/CLI/E2E compatibility gate — 298 passed.
- Unit coverage proves restart-durable private payloads, no secret values in
  SQLite plans, target/source stale rejection, all seven operation families,
  standalone catalog writes, verified apply, and verified rollback.

### Re-evaluation conditions

Replace the local `0600` payload store with encryption or Keychain-backed
envelopes before adding multi-user access, cloud synchronization, or a threat
model where another local account can read the operator's files.

## 2026-07-17 — Harden and verify Desktop transport

### Purpose

Make local and remote Desktop connections behaviorally consistent, restore
authenticated remote events without exposing bearer tokens to JavaScript,
surface launch failures immediately, and enable a production CSP.

### Decision and rationale

- Route local and remote Desktop HTTP through one Rust request builder that
  supports GET, POST, PUT, PATCH, and DELETE. Local mode uses the configured
  `settings.local.api_url`; remote mode adds the Keychain-backed bearer in Rust.
- Keep SSE for native clients, but use authenticated bounded
  `GET /events/poll` through the Rust bridge for the WebView. Direct
  `EventSource` cannot attach the Keychain bearer safely.
- Return typed startup results from Desktop lifecycle scripts. Store the latest
  `connection-state` payload so the WebView can subscribe first and then read
  the current state without losing a setup-time failure event.
- Enable a restrictive Tauri CSP with packaged-only scripts/styles, Tauri IPC,
  loopback API connections, and HTTPS connection targets. Remove Google Fonts
  and inline style attributes so the packaged UI remains offline-capable
  without broadening script or style origins.
- Treat remote PUT/DELETE `403` and PATCH `/health` `405` as expected policy
  evidence, not transport failures. Those requests reached the daemon; the
  localhost-only route guard and FastAPI method contract rejected them.

### Alternatives considered

- Put the bearer token in JavaScript or `desktop.toml`: rejected because it
  breaks the Keychain trust boundary.
- Keep direct remote `EventSource`: rejected because browser EventSource has no
  safe bearer injection path here.
- Leave `csp: null` or allow remote font styles: rejected because the Desktop
  app should not require network-loaded executable/style content.
- Infer verb support from a method allowlist alone: rejected; a loopback HTTP
  server test now proves the shared Rust client sends all five verbs, bearer
  headers, and request bodies.

### Verification

- Focused Desktop/remote suite:
  `145 passed in 5.11s`.
- Rust Desktop suite:
  `32 passed; 0 failed`.
- Live isolated `agentd` + Caddy internal-TLS gateway:
  `smoke-remote-client: ok`.
- Temporary device result:
  `gateway_smoke device=Ffao7Y8ISCvoAu-6lTr3hA result=ok`; the device was
  revoked, both processes were stopped, and ports 8767/8443 had no listener.
- The live smoke covered GET health, POST fleet probe, PUT/PATCH/DELETE policy
  boundaries, authenticated `/events/poll`, and SSE.

### Release boundary

This evidence is credential-independent and covers source behavior, the local
TLS gateway, and Desktop transport. Apple Developer ID signing, notarization,
and updater publication require external credentials and are not claimed by
this entry.

## 2026-07-17 — Make environment observations the primary Desktop surface

### Purpose

Turn the normalized `/environments` model into the operator's main cross-agent
view without duplicating the older discovery, inventory, and fleet modules.

### Decision and rationale

- Render the seven built-in environments as a master-detail view with separate
  CLI, config, capability, runtime, Desktop, and IDE surface observations.
- Keep every proof value and action string escaped through the shared
  `Ao.escapeHtml` boundary before inserting rendered markup.
- Use the shared short-lived `Ao.DataCache` for the list, while detail selection
  and manual refresh call their dedicated environment endpoints.
- Preserve mature tool, inventory, harness, and fleet panels as Environments
  subviews instead of rewriting or removing them.

### Verification

- `node --check apps/web/api.js`
- `node --check apps/web/ui/environment-manager.js`
- `node --check apps/web/app.js`
- `rtk uv run pytest tests/test_web.py tests/test_api.py -k "environment or web" -q`
  — 85 passed.
