# agentic-os

Local Agent Environment Manager for observing and safely changing heterogeneous
coding and orchestration environments on one Mac.

`agentic-os` is not a harness, not a second OpenClaw, and not an agent runtime.
It is the management layer underneath harnesses such as OpenClaw, Hermes, Codex,
Claude Code, Gemini CLI, and OpenCode: it records configured harness instances,
starts and observes harness runs, stores local run evidence, exposes a thin
control UI, and evaluates launch-time policy.

The Desktop app is organized around Home, Environments, Sessions, Capabilities,
Changes, and Settings. Existing API and CLI labels
such as `agents`, `sessions`, `skills`, `mcp`, and `policy` remain stable
interface names for now, but the product language is:

| Previous wording | Harness Manager wording | Existing interface labels |
|------------------|--------------------------|---------------------------|
| Agent Registry | Harness Instance Registry | `/agents`, `agentctl agents` |
| Agent Session | Harness Run / Harness Session | `/sessions`, `agentctl sessions` |
| Agent Policy | Harness Launch Policy | `/policy`, `agentctl policy` |
| Skills / MCP | Shared Capability Catalog | `/skills`, `/mcp`, `agentctl skills`, `agentctl mcp` |
| Adapter-profile wording | Harness Instance Profile | `specs/007-harness-instance-profile-p3.7.md` |

Phase positioning:

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P0 | daemon, CLI, configured runners, process/log/session records | Harness Instance Registry and Harness Run lifecycle | local launch, stop, retry, logs, artifacts | harness internals, planning, tool execution |
| P1 | deterministic session evidence and review pointers | auditable run evidence for downstream compilers | summaries, review pointers, evidence paths | durable memory compilation, embeddings, RAG |
| P2 | thin static UI | operator control surface over daemon APIs | status, bounded logs, review UI, catalog placeholders | browser subprocesses, IDE, chat UI |
| P3 | catalog/policy registries and evaluator | Shared Capability Catalog plus Harness Launch Policy | descriptive capability records, deterministic policy decisions | installing capabilities, starting MCP servers, live tool enforcement |
| P3.5 | launch policy gate on run creation | Harness Launch Policy applied before spawning a run | allow / deny / approval-required audit trail | per-tool runtime enforcement |
| P3.6 | retry bypass closure and clearer policy errors | all run-start paths share the same launch gate | retry policy audit, CLI/UI error display | approval workflow or harness-internal enforcement |
| P3.7 | harness instance profile schema | management metadata for each harness instance | config path, workspace roots, launch/health/attach/log commands, default provider | harness internals, planning, tool execution |
| P4 | fleet control plane goals spec | performance-first single-machine fleet control plane charter | goals, SLO, non-goals, governance principles | health probe implementation, drift detection, audit workflow |
| P5 | fleet inventory and health | fleet health monitoring, capacity enforcement, config drift detection | health probes, drift events, capacity 429, fleet API/CLI/UI | audit workflow, governance closed loop |
| P6 | governance closed loop | auditable workflow across all domains, deprecation lifecycle, bounded log reads, policy coverage | audit events, deprecation, log reader isolation, policy bypass verification | multi-user RBAC, cloud sync, approval workflow UX |
| P7 | human approval workflow | local operator approval for launch-policy decisions | approval requests, approve/reject API/CLI/UI, audit links | RBAC, notifications, live in-harness tool approval |
| P8 | SLO benchmark harness | measurable local control-plane performance targets | latency benchmark, diagnostics resource snapshot, JSON report | hosted telemetry, continuous monitoring, automatic tuning |
| P9 | deprecation lifecycle completion | structured sunset governance for catalog and policy records | reason/replacement/sunset metadata, un-deprecate, opportunistic auto-disable | package management, delete/purge workflow, scheduler |
| P5+ | configuration scope mapper | multi-scope config view per harness instance | read, merge, display effective config across scopes | modifying config files, harness-internal config loading |
| P6+ | workflow surface catalog | inventory of hooks/commands/skills/subagents/MCP across harness scopes | scan paths, classify surfaces, show merged view per project, diff between scopes | executing hooks, loading skills, starting MCP servers, modifying configs |
| P7+ | evidence and audit timeline | chronological view of all events per session/harness | timeline construction, event correlation, per-session history | modifying source events, live event streaming |
| P8+ | approval queue enhancement | local operator approval for launch-policy decisions (workflow refinement) | approval queue view, approve/reject lifecycle, audit links | RBAC, notifications, live in-harness tool approval |
| P9+ | harness dashboard v2 | daily operator control surface over all daemon APIs | organized views, session timeline, approval queue, catalog display | chat UI, IDE integration, agent loop execution |
| P10 | safe native config editing | safe write layer for workflow surfaces, harness-native config, and agentic-os config | dry-run patch, schema validation, hybrid backup, rollback, surface/config writers, audit | harness runtime, P7 approval for config writes, desktop app (P11), iOS remote (P12), cloud sync |
| P11 | desktop app shell | macOS-validated Tauri dev shell over static web UI with local daemon lifecycle | tray, embedded UI server, `desktop-daemon.sh`, `desktop.toml` settings placeholders | packaged `.app` (done P11.5), iOS app (P12.5) |
| P11.5 | **complete** — packaged macOS app | ad-hoc-signed standalone `.app` with bundled agentd/UI resources and convergent lifecycle | `prepare-desktop-bundle.sh`, relocatable managed CPython, Tauri bundle resources, release path resolution | Developer ID signing, notarization, DMG distribution, auto-update |
| P12 | **complete** — remote access adapter | Remote Access Adapter: remote gateway / reverse tunnel, pairing, token, revoke, event stream; `agentd` stays on `127.0.0.1` | `desktop.toml` remote wire-up, reference gateway, SSE client, pairing UX with gateway Bearer boundary | specific tunnel product (frp/Tailscale/CF/ngrok), Keychain persistence (P12.5), iOS app (P12.5), cloud sync |
| P12.5 | **complete** — keychain + iOS companion | secure `auth_token` persistence, desktop remote reconnect, iOS remote client skeleton | macOS Keychain token storage, `connection.mode=remote` Bearer proxy, iOS SwiftUI companion + Keychain | App Store release, push notifications, full iOS UI polish |
| P13 | **complete** — remote approval loop | surface P7 approval lifecycle on the remote `/events` stream; explicit, tested remote approve/reject over the gateway Bearer boundary | `governance` approval events in remote stream, gateway-reachable `/approvals` contract + tests, conscious remote-approve security posture | new approval state machine (P7 owns it), RBAC, push notifications, iOS UI polish (P14+) |
| P14 | **complete** — remote token lifecycle | opt-in token TTL + in-place token rotation, backward-compatible with P12 forever-tokens | `expires_at` column + in-place migration, `validate_token` expiry check, localhost-only `POST /remote/devices/{id}/rotate`, `expires_at` in device listing | default-on TTL policy, silent refresh UX, APNs push (P16) |
| P15 | **complete** — remote HTTPS hardening | client-side transport policy: refuse Bearer / Keychain writes to cleartext non-loopback gateways | `validate_remote_gateway` in desktop Rust, iOS `normalizedGatewayURL`, loopback `http://` allowed for local smoke | certificate pinning, mTLS, APNs push |
| P16 | **complete** — catalog patch UI | first operable UI vertical: catalog MCP enable/disable with dry-run diff, apply, patch history, rollback | `apps/web/api.js`, `ui/catalog-editor.js`, `ui/rollback.js`; local-mode write gating | harness-native config editing (P17), remote writes (P25) |
| P17 | **complete** — harness config patch UI | parameterized `ui/config-editor.js` for harness-native path patches with `base_mtime` optimistic lock | Harness tab effective → dry-run diff → apply → rollback; 409 re-preview; 422/403 inline | agentic-os config editor instance (P18), remote writes (P25) |
| P18 | **complete** — run profile backend patch | profile TOML delete/diff/rollback via `SafeEditEngine`; single writer; bound-profile cascade | `DELETE /profiles/{name}`, `GET /profiles/{name}/diff`, engine-backed upsert/bind | profile UI (P19) |
| P19 | **complete** — profile / provider UI | form-based `ui/profile-editor.js` with dry-run `base_mtime`, cascade delete UX, project bind display | Agents tab profile editor; env-var name only for `default_env` | registry editor (P21) |
| P20 | **complete** — registry editor backend | safe write to `agents.toml` via engine; `validate_registry` gate; `registry.reload()` on write/rollback | `POST /registry/agents`, `POST /registry/agents/{id}/disable`, `GET /registry/schema` | registry UI (P21) |
| P21 | **complete** — registry editor UI | form-based `ui/registry-editor.js` with schema-driven `cwd_mode` dropdown and patch rollback | Agents tab registry editor; redacted diff display | MCP/skill/policy rollback UI (P23) |
| P22 | **complete** — MCP/skill/policy rollback backend | DB-native `control_plane_history` with mutation envelope + per-entity history/rollback routes | `GET/POST /{skills,mcp,policy}/{id}/history|rollback`; redacted snapshots | catalog rollback UI (P23) |
| P23 | **complete** — MCP/skill/policy management UI | form-based `ui/control-plane-editor.js` with history/rollback per entity | Skills/MCP tab edit + disable + history; env-name only; no live MCP connect | remote writes (P25) |
| P24 | **complete** — approval workbench | per-request cards with argv/cwd/policy context; approve/reject/retry | `ui/approval-workbench.js`; SSE in remote mode | in-harness live tool approval |
| P25 | **complete** — remote operator console | `GET /remote/affordances`; hide localhost-only admin in remote mode | `ui/remote-console.js`; token status without value leakage | certificate pinning |
| P26 | **complete** — project setup import/export | portable bundle export; dry-run diff then gated import | `GET /setup/export`, `POST /setup/import`; `import_export.py` | package management |
| P27 | **complete** — desktop product polish | diagnostics, version stub, bounded redacted logs zip | `GET /version`, `GET /setup/logs.zip`, `ui/product-polish.js` | auto-update infra |
| P28 | **complete** — product smoke + provider/model launch wiring | behavior-level smoke harness; profile model/provider reach spawned argv | `scripts/smoke-product.sh`; `model_arg` / `provider_env` registry templating | harness runtime changes |
| P29 | **complete** — workspace / project manager + dashboard-lite | server-side workspace registry; cwd threading; read-only dashboard | `GET/POST/PUT /workspaces`, `GET /workspaces/dashboard`, `ui/workspace-manager.js` | file explorer, cloud sync |
| P30 | **complete** — provider / model switchboard UI | one-click profile switch; shows resolved session provider/model | `ui/provider-switchboard.js` | billing API, harness runtime |
| P31 | **complete** — agent content editor | form-based skill/MCP/policy/hook editing with history + policy evaluate | extended `ui/control-plane-editor.js` | MCP process start, marketplace |
| P32 | **complete** — run template / task launcher | saved launchers with argv preview; `source_template_id` on sessions | `/run-templates`, `ui/run-template-launcher.js` | scheduling, background loop |
| P33 | **complete** — daily operator dashboard | full 總覽 workbench; affordance-driven quick actions | `ui/daily-dashboard.js` | chat UI, RBAC |
| P34 | **complete** — tool discovery + config inventory | read-only presence/version/config summary per tool | `tool_discovery.py`, `config_inventory.py`, `/tools/discovery`, `/tools/inventory` | config sync, secret reads |
| P35 | **complete** — vibe coding runtime adapter | launch/stop/retry/logs/evidence zip for codex/claude headless runs | `ui/vibe-coding-launcher.js`, evidence zip endpoint | chat UI, agentic runtime launch |
| P36 | **complete** — session discover / bind / attach | register external sessions and attach previews | `attach.py`, `/sessions/discover`, `/sessions/bind` | modifying external runtimes |
| P37 | **complete** — agentic runtime inventory | read-only OpenClaw/Hermes/n8n capability inventory | `agentic_inventory.py`, `/agentic/inventory` | starting/stopping agentic runtimes |
| P38 | **complete** — dual-track dashboard v2 | two-column 總覽 (Vibe Coding / Agentic Runtime) | `ui/dashboard-v2.js` | new backend aggregator |
| P39 | **complete** — live session radar | observe-first: real claude/codex session stores surfaced with resume + open-terminal actions | `live_sessions.py`, `/sessions/live`, dashboard Live Sessions card | writing to external stores, file watching, cross-machine |
| P40 | **complete** — capability radar | real skills/MCP/plugins/memory names per tool (claude/codex/gemini/qwen/opencode/cursor) | `capability_inventory.py`, `/tools/capabilities`, 工具 tab capability cards | writing tool configs, secret values, content reads |
| P41 | **complete** — transcript preview | tail preview of any discovered session's conversation | `read_transcript_tail`, `/sessions/live/transcript`, radar inline panel | sending messages, full-transcript search |
| P42 | **complete** — MCP alignment | cross-tool MCP matrix + safe copy/remove via P10 safe-edit (dry-run default, backup, rollback; values never leave the daemon) | `mcp_alignment.py`, `/tools/mcp/*`, 工具 tab matrix | creating/editing servers, skills/plugins writes, bulk sync |
| P43 | **complete** — chat launcher | chat-shaped front on the policy-gated run path: message → `POST /sessions`, reply = session stdout with status + log links; denials render as system bubbles | `ui/chat-launcher.js`, 聊天 tab, sidebar `.tab-desc` sublabels | new endpoints, LLM routing, multi-turn process state, server-side chat history |
| P44 | **complete** — Environment foundation | one built-in adapter table, normalized CLI/config/capability/runtime/Desktop/IDE evidence, shared health probes and native-session observation, unified launch decisions | `environment_*`, `probe_service.py`, `native_session_service.py`, `launch_decision.py`, `/environments` | dynamic adapters, automatic config reconciliation |
| P45 | **complete** — verified Changes | durable redacted plans with preview, stale checks, deterministic pre-write backup linkage, activation-aware verification, and drift-safe rollback across MCP/config/catalog/profile/registry writes | `change_*`, `/changes`, compatibility mutation routes, P10 `SafeEditEngine` | generic mutation DSL, cloud approval, secret values in plan/API payloads |
| P46 | **complete** — Desktop operator experience | six daily-use areas with Environment Manager, Change Center, owner-linked Settings, attention routing, keyboard focus, and responsive layouts | `ui/navigation.js`, `environment-manager.js`, `change-center.js`, `settings-home.js`, shared data cache | frontend framework, hidden legacy navigation, duplicated write controls |
| P47 | **complete** — packaged release proof | reproducible arm64 `.app`, source-only bundled Python, ad-hoc resource seal that remains valid after daemon launch, product/remote smoke, tray lifecycle, crash-orphan recovery | app-only `desktop:build`, package tests, `codesign --verify`, live packaged-app checks | Developer ID/notarization, DMG, updater feed, Intel/Windows/Linux release validation |

**Current (2026-07-17):** P44–P47 consolidate the mature substrate into a
Local Agent Environment Manager, route supported mutations through durable
Verified Changes, replace the fragmented top-level UI with six operator areas,
and prove the packaged macOS lifecycle.

Session Evidence v1 clarifies ownership: agentic-os owns harness-run evidence, evidence paths,
bounded logs, and summary/review pointers. session2memory owns formal memory compilation,
review-first durable suggestions, and downstream HKS ingestion. The compatibility `agentctl memory`
commands remain available, but new workflows must consume `metadata.json`, `events.jsonl`,
stdout/stderr JSONL, and `artifacts/manifest.json`.

## P0 Scope

P0 is not a UI, memory system, or Claude OS clone. It is a local daemon and CLI
that can reliably register harness instances and start, stop, list, inspect, and
log harness runs.

Read the first spec: [specs/001-daemon-runtime.md](specs/001-daemon-runtime.md).

## One-command local start

Start the daemon and static UI together:

```bash
rtk bash scripts/start-local.sh
```

The script starts `agentd` on `127.0.0.1:8767` and the web UI on
`127.0.0.1:5173`. Press `Ctrl-C` to stop both.

Optional overrides:

```bash
AGENTIC_OS_PORT=8797 AGENTIC_OS_UI_PORT=5181 rtk bash scripts/start-local.sh
```

## Desktop app (P11 / P11.5 / P46 / P47)

macOS arm64-validated Tauri app. Requires pnpm + Rust toolchain to build.
The packaged UI exposes Home, Environments, Sessions, Capabilities, Changes,
and Settings; mature editors remain available as subviews.

**P11 — dev shell** (merge gate: `desktop:dev`):

```bash
pnpm install
pnpm desktop:dev      # tray + ui:5173 + agentd:8767 + webview
```

**P11.5 — packaged `.app`** (merge gate: `desktop:build` smoke):

```bash
pnpm desktop:build  # builds the .app only; no Finder-dependent DMG step
codesign --verify --deep --strict --verbose=4 \
  apps/desktop/src-tauri/target/release/bundle/macos/agentic-os.app
open apps/desktop/src-tauri/target/release/bundle/macos/agentic-os.app
```

The packaged app serves UI assets directly from Tauri, so port `5173` does not
open. Its bundled daemon runs Python with bytecode writes disabled so launch
does not mutate signed resources. After tray Quit, both `8767` and `5173` must
have no listeners.

Local builds use Tauri's ad-hoc identity `-`, which seals the bundle but does
not establish a publisher identity. Downloaded builds can still require manual
approval in macOS Privacy & Security. Public distribution remains blocked on a
Developer ID Application certificate, notarization credentials, a DMG release
step, and an updater endpoint. Intel macOS, Windows, and Linux packages are not
validated. See [Tauri macOS signing](https://v2.tauri.app/distribute/sign/macos/).

**P12 — remote access** (merge gate: pairing + SSE auth + gateway smoke):

```bash
uv run agentd serve
# optional reference gateway:
caddy run --config examples/remote-gateway/Caddyfile

# desktop Settings → Start pairing → complete from remote client
bash scripts/smoke-remote-client.sh https://127.0.0.1:8443 "$TOKEN"
```

See `examples/remote-gateway/README.md` and `apps/ios/README.md`. `agentd` stays on `127.0.0.1` only.

## Run P0 Locally

Terminal 1:

```bash
uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Terminal 2:

```bash
uv run agentctl agents list
uv run agentctl run shell --cwd "$PWD" --message "OK"
uv run agentctl sessions list
uv run agentctl logs <session_id>
uv run agentctl retry <session_id>
```

Real agent smoke examples:

```bash
uv run agentctl run openclaw --cwd "$PWD" --message "只輸出 OK"
uv run agentctl run hermes --cwd "$PWD" --message "只輸出 OK"
```

Required local smoke is `shell`. Run real agent smoke when OpenClaw or Hermes CLIs are available; if a real agent fails due to its own gateway, auth, model, or CLI state, keep the session id and `agentctl logs <session_id>` output as proof that agentic-os launched it and captured the upstream failure.

2026-05-27 machine verification: `rtk uv run agentctl run openclaw --api http://127.0.0.1:8777 --cwd "$PWD" --message "只輸出 OK"` launched `s_17195fb7386642eca681504d67d92554` and captured OpenClaw's upstream "No target session selected" error; `rtk uv run agentctl run hermes --api http://127.0.0.1:8777 --cwd "$PWD" --message "只輸出 OK"` succeeded as `s_a36fbb159d754b01b069fd8018083b35` with `stdout OK`.

`stop` is only for sessions that are still `running`; the `shell` smoke exits immediately.
For a safe local stop demo, start a daemon with a temporary long-running agent:

```bash
tmp_registry="$(mktemp)"
cat > "$tmp_registry" <<'TOML'
[[agents]]
id = "sleep"
label = "Sleep"
command = ["/bin/sleep", "30"]
cwd_mode = "optional"
stop_policy = "process_group"
TOML
uv run agentd serve --port 8768 --state-dir .agentic-os-stop --registry "$tmp_registry"
```

Then run and stop it from another terminal:

```bash
uv run agentctl run sleep --api http://127.0.0.1:8768 --cwd "$PWD" --message "ignored"
uv run agentctl stop <running_session_id> --api http://127.0.0.1:8768
```

## Run P1 Memory Pipeline

P1 turns a completed session into reviewable local memory:

```text
session logs -> session summary -> review queue -> approved memory -> search
```

Start the daemon:

```bash
rtk uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Run a shell session and promote its summary:

```bash
rtk uv run agentctl run shell --cwd "$PWD" --message "approved memory fact"
rtk uv run agentctl memory summarize <session_id>
rtk uv run agentctl memory review create <session_id>
rtk uv run agentctl memory review list
rtk uv run agentctl memory approve <review_item_id>
rtk uv run agentctl memory search approved
```

Memory promotion is explicit. `review create` queues a deterministic summary;
`approve` creates the durable memory record.

## Run P2 Thin UI

Start the daemon:

```bash
rtk uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Start the no-build static UI:

```bash
cd apps/web
python -m http.server 5173
```

Open `http://127.0.0.1:5173`. The UI defaults to
`http://127.0.0.1:8767`; edit the API URL field if the daemon uses another
port.

P2 shows harness instances, harness runs, bounded logs, memory review/approved
memory, and placeholder Shared Capability Catalog views. The daemon remains the
only process owner.

## Run P3 Shared Capability Catalog / Harness Launch Policy

Start the daemon:

```bash
rtk uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Use the CLI registry path:

```bash
rtk uv run agentctl skills upsert reviewer --label "Reviewer" --source workspace --tag review
rtk uv run agentctl skills list
rtk uv run agentctl mcp upsert filesystem --label "Filesystem MCP" --transport stdio --env-key MCP_TOKEN
rtk uv run agentctl mcp list
rtk uv run agentctl policy set shell --skill reviewer --mcp filesystem --tool read --model local-model --cwd-root "$PWD"
rtk uv run agentctl policy evaluate shell --skill reviewer --mcp filesystem --tool read --model local-model --cwd "$PWD"
```

Use the daemon API path:

```bash
curl http://127.0.0.1:8767/skills
curl http://127.0.0.1:8767/mcp
curl http://127.0.0.1:8767/policy
```

Use the UI path by starting `apps/web` as in P2 and opening the Skills / MCP tab.
The tab name is still the interface label, but its positioning is Shared
Capability Catalog. It shows catalog rows, Harness Launch Policy summary, and
deterministic evaluation results.

P3 does not start MCP servers, install catalog entries, execute external tools,
enforce live harness loops, or take over Hermes/OpenClaw. P3 does not execute external tools during policy evaluation.
Secrets must not be stored: use environment variable names such as `MCP_TOKEN`,
not token values. Command and URL previews are redacted before storage/display.

## Run P3.5/P3.6 Harness Launch Policy-Aware Run

P3.5 wires Harness Launch Policy into the run creation path. P3.6 closes the
retry bypass and improves error display.

Start the daemon:

```bash
rtk uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Set a policy that restricts where `shell` can run:

```bash
rtk uv run agentctl policy set shell --cwd-root "$PWD" --tool '*' --model '*'
```

Run inside the allowed root (succeeds):

```bash
rtk uv run agentctl run shell --cwd "$PWD" --message "allowed"
```

Run outside the allowed root (denied with audit trail):

```bash
rtk uv run agentctl run shell --cwd /tmp --message "blocked"
# HTTP 403: decision=deny  cwd is outside allowed roots for shell  session_id=s_...
```

Inspect the denied session's events:

```bash
rtk uv run agentctl sessions events <session_id>
```

Set approval-required on session start:

```bash
rtk uv run agentctl policy set shell --cwd-root "$PWD" --tool '*' --model '*' --approval-tool session.start
rtk uv run agentctl run shell --cwd "$PWD" --message "needs approval"
# HTTP 409: decision=approval_required  session.start requires approval for shell  session_id=s_...
```

Retry respects the same policy gate: a denied Harness Session cannot be retried
into a running process if the policy still denies it.

The UI Run button (Agents tab) and Retry button (Sessions tab) show
`decision / reason / session_id` on 403/409.  The Logs tab shows session events
in a collapsible panel below the log output.

## Run P5 Fleet Inventory + Health

Start the daemon:

```bash
rtk uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Query fleet health, capacity, and events:

```bash
rtk uv run agentctl fleet health
rtk uv run agentctl fleet health shell
rtk uv run agentctl fleet capacity
rtk uv run agentctl fleet events
rtk uv run agentctl fleet events --agent shell --type config_drift_detected
rtk uv run agentctl fleet probe
```

Use the daemon API path:

```bash
curl http://127.0.0.1:8767/fleet/health
curl http://127.0.0.1:8767/fleet/capacity
curl http://127.0.0.1:8767/fleet/events
curl -X POST http://127.0.0.1:8767/fleet/probe
```

Use the UI path by starting `apps/web` as in P2 and opening the Fleet tab.
The tab shows instance health, capacity utilization, and fleet events. The
Probe Now button triggers an on-demand health probe cycle.

P5 implements G1 (audit-everything: health state changes and config drift
produce fleet events), G2 (failure isolation: probe timeouts do not block other
probes), G3 (config drift as first-class signal: version/fingerprint changes
recorded as drift events), and G4 (capacity bounded and visible: 429 on session
limit, queryable utilization). P5 does not implement G5 (deprecation workflow)
or G6 (governance closed loop) — those are P6.

## Run P6 Governance Closed Loop

Start the daemon:

```bash
rtk uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Query audit trail, policy coverage, and deprecate capabilities:

```bash
rtk uv run agentctl audit events
rtk uv run agentctl audit events --domain skill --type skill_deprecated
rtk uv run agentctl audit coverage
rtk uv run agentctl skills deprecate reviewer
rtk uv run agentctl mcp deprecate filesystem
rtk uv run agentctl policy deprecate shell
```

Use the daemon API path:

```bash
curl http://127.0.0.1:8767/audit/events
curl http://127.0.0.1:8767/audit/events?domain=governance
curl http://127.0.0.1:8767/audit/policy-coverage
curl -X POST http://127.0.0.1:8767/skills/reviewer/deprecate
```

Use the UI by opening the Fleet tab — the Audit Trail section shows governance
events with domain filtering.

P6 closes the governance loop declared in P4 (specs/008):
- G1 end-to-end: every skill/MCP/policy CRUD mutation and every run policy
  decision produces an audit event
- G2 enforcement: log reads are bounded at 5000 lines by default; truncation
  is audited
- G5: skills, MCP servers, and policies support deprecation — deprecated items
  produce warnings but remain functional
- G6: every run records whether it started with or without a policy evaluation;
  `audit coverage` reports uncovered runs

## Run P8 SLO Benchmark

Start a dedicated test daemon; do not point the benchmark at live operator
state:

```bash
rtk uv run agentd serve --port 8797 --state-dir .agentic-os-bench --registry examples/agents.toml
```

Run the benchmark with an explicit test daemon API:

```bash
rtk uv run agentctl bench slo --api http://127.0.0.1:8797 --iterations 100 --output .agentic-os-bench/slo-report.json
curl http://127.0.0.1:8797/diagnostics/resources
```

`bench slo` fails fast when `--api` is omitted.

## P1/P2/P3/P3.5/P3.6/P5/P6/P7/P8/P9 Limitations

P1-P9 intentionally do not include:

- LLM-generated summaries; summaries are deterministic from session metadata
  and stdout/stderr logs.
- Embeddings, vector DB, LanceDB, Redis, or remote sync.
- Live policy enforcement inside Hermes/OpenClaw harness loops.
- MCP server process ownership, browser-side subprocess work, or UI indexing.
- Multi-user auth, RBAC, cloud sync, chat UI, Kanban, Electron, Tauri, planner,
  executor, tool loop, memory reasoning, browser driver, or task decomposition.

## How to verify the product (P28)

Run the behavior-level smoke harness. It starts an isolated `agentd`, verifies
all built-in Environment adapters and six-surface detail, exercises a
non-mutating Change preview through verified apply and exact rollback, then
checks launch/config/import/remote/approval flows:

```bash
bash scripts/smoke-product.sh
```

On failure the script exits non-zero and prints the first failing step plus
report paths (`report.txt`, `report.json`, `smoke.log` under a temp directory).
Override the smoke workspace with `SMOKE_PRODUCT_DIR=/tmp/my-smoke`.

Release gate before merge:

```bash
rtk uv run pytest -q
rtk uv run ruff check .
cd apps/desktop/src-tauri && cargo test
cd ../../..
bash scripts/smoke-product.sh
pnpm desktop:build
codesign --verify --deep --strict --verbose=4 \
  apps/desktop/src-tauri/target/release/bundle/macos/agentic-os.app
```

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
```
