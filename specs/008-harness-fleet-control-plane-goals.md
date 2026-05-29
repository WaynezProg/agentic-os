# 008 — Harness Fleet Control Plane Goals (P4)

Status: Draft
Date: 2026-05-29

## Positioning

P4 redefines the overall goal envelope for agentic-os. P0–P3.6 proved the
substrate works: one daemon can register harness instances, launch/stop/retry
runs, capture logs, manage a capability catalog, and enforce launch policy.
P4 declares what the mature system must be and — equally important — what it
must never become.

agentic-os is a **performance-first, single-machine fleet control plane** for
local coding and orchestration harnesses. It manages the fleet; it does not
join the fleet.

| Layer | Owns | Does not own |
|-------|------|--------------|
| Fleet inventory | instance profiles, health probes, version/config metadata | harness internals, tool loops, planners |
| Run lifecycle | launch, stop, retry, log capture, artifact storage | in-harness execution, prompt routing, model calls |
| Capability catalog | descriptive skill/MCP records, secret-redacted previews | capability installation, MCP server processes |
| Launch policy | deterministic allow/deny/approval-required gate | per-tool runtime enforcement, in-harness policy |
| Governance | audit trail, failure isolation, config drift detection | approval workflow UX, cloud sync, multi-user RBAC |

## Goals

1. **Single-process fleet manager** — one `agentd` daemon manages all local
   harness instances (OpenClaw, Hermes, Codex, Claude Code, Gemini CLI,
   OpenCode, and future harnesses) without spawning additional manager
   processes.

2. **Performance-first contract** — API reads ≤ 50 ms p99, writes ≤ 200 ms
   p99, full health probe round ≤ 5 s for up to 50 instances. The daemon stays under
   a fixed resource budget regardless of fleet size.

3. **Fleet inventory with health** — each harness instance has a profile
   (launch, health, attach, log commands), and the daemon probes health on a
   configurable interval, surfacing up/degraded/down per instance.

4. **Version and config drift detection** — the daemon can read and compare
   harness version strings and config fingerprints, flagging when an instance
   drifts from its declared baseline.

5. **Observable run lifecycle** — every launch, stop, retry, policy decision,
   and failure is an auditable event with a durable session id.

6. **Failure isolation** — a crashing or stuck harness instance must not block
   the daemon, other instances, or the control UI. Process group isolation
   already exists (P0); P4 extends the principle to health probes and log
   readers.

7. **Governance-ready audit surface** — all policy decisions, health state
   transitions, config drift alerts, and capacity events are stored as
   queryable records. P6 can build auditable workflows on top without
   retroactive schema changes.

## Service Level Objectives (Provisional)

These targets apply to the `agentd` daemon on a single developer machine.
"Provisional" means they are design targets, not contractual SLAs; P5
implementation will benchmark and may tighten or relax specific numbers.

### Latency

| Operation | Target | Measurement |
|-----------|--------|-------------|
| GET /agents, /sessions (list) | p99 ≤ 50 ms | wall-clock, 100 concurrent instances registered |
| GET /sessions/{id}, /sessions/{id}/events | p99 ≤ 50 ms | wall-clock |
| POST /sessions (run creation + policy eval) | p99 ≤ 200 ms | wall-clock, policy rule set ≤ 50 rules |
| POST /sessions/{id}/retry | p99 ≤ 200 ms | wall-clock |
| Health probe round (all instances) | ≤ 5 s total | wall-clock, ≤ 50 instances |

### Parallelism

| Dimension | Limit |
|-----------|-------|
| Registered harness instances | ≤ 100 |
| Concurrent running sessions | ≤ 50 |
| Concurrent health probes in-flight | ≤ 10 (windowed) |

### Resource Budget

| Resource | Budget | Condition |
|----------|--------|-----------|
| Daemon RSS memory | ≤ 256 MB | 100 registered instances, 50 concurrent sessions |
| Daemon CPU | ≤ 1 core sustained | normal operation (not counting spawned harnesses) |
| SQLite WAL size | ≤ 64 MB | before automatic checkpoint |
| State directory disk | ≤ 1 GB | excluding harness-produced artifacts |

## Non-Goals

These items are explicitly outside the scope of agentic-os at any phase.
They are not "future work" — they are structural exclusions.

### Never-goals (architectural boundary)

1. **Not a harness** — agentic-os does not execute tool loops, plan tasks,
   route prompts, call models, or run code on behalf of a harness. It
   manages harnesses; it does not become one.

2. **Not a runtime** — no embedded LLM inference, no vector DB, no
   embedding pipeline, no RAG. Deterministic logic only in the daemon.

3. **Not multi-machine** — fleet means one developer machine. No cluster
   coordination, no remote daemon discovery, no distributed consensus, no
   cloud sync.

4. **Not multi-user** — single operator. No auth, no RBAC, no tenant
   isolation, no shared state across users.

5. **Not a UI framework** — the control surface is a thin static page or
   CLI. No React, no Electron, no Tauri, no browser subprocess, no IDE
   plugin.

6. **Not a package manager** — the capability catalog describes skills and
   MCP servers. It does not install, update, or version them.

### Phase non-goals (excluded from P4 but may appear in P5/P6)

7. **No health probe implementation in P4** — P4 defines the contract
   (profile fields, health state enum, probe interval config); P5 implements
   the probe loop.

8. **No drift detection implementation in P4** — P4 defines what drift
   means (version mismatch, config fingerprint change); P5 implements the
   detection.

9. **No auditable workflow in P4** — P4 defines the event schema and
   governance principles; P6 builds the audit-trail query surface and
   failure isolation enforcement.

10. **No capacity planning enforcement in P4** — P4 defines the resource
    budget and parallelism limits; P5/P6 implement the enforcement and
    backpressure.

## Governance Principles

These principles guide P5/P6 implementation decisions. P4 declares them;
P5/P6 must satisfy them.

### G1. Audit-everything

Every state transition (run start, stop, retry, policy decision, health
state change, config drift alert) produces a durable, timestamped event
record with a stable session or instance id. No silent mutations.

### G2. Failure isolation

A failing harness instance must not cascade. Specifically:
- A hanging health probe must timeout (configurable, default 10 s) without
  blocking probes for other instances.
- A crashing harness run must not corrupt shared daemon state (SQLite,
  in-memory registries).
- A stuck log reader must not block the event loop or API responses.

### G3. Config drift is a first-class signal

When an instance's observed version or config fingerprint diverges from its
declared baseline, the daemon records a drift event. The operator decides
whether to update the baseline or fix the instance — the daemon does not
auto-remediate.

### G4. Capacity is bounded and visible

The daemon enforces the parallelism limits from the SLO table. When a limit
is reached, new run requests receive a 429 with a clear reason, not a silent
queue or degraded performance. Current utilization is queryable.

### G5. Deprecation before removal

Harness instance profiles, policy rules, and capability catalog entries are
deprecated before removal. Deprecated items produce warnings in CLI/UI and
events in the audit trail but remain functional until explicitly removed.

### G6. No silent privilege escalation

A harness run may not acquire capabilities (tools, models, cwd roots) beyond
what its launch policy allows. This is already enforced at launch time
(P3.5/P3.6); the governance principle extends it: future features must not
introduce paths that bypass the policy evaluator.

## Phase Roadmap

P4 is a goals-and-boundaries spec. It declares contracts that P5 and P6
must satisfy but does not implement them.

| Phase | Scope | Relationship to P4 |
|-------|-------|--------------------|
| P4 | This spec: goals, SLO, non-goals, governance principles | Defines the contract |
| P5 | Fleet inventory, health probes, version/config drift, launch/attach/log observability | Implements G1, G2, G3, G4 (implemented) |
| P6 | Governance closed loop: auditable workflow across memory/MCP/skill/session/policy, performance gate, failure isolation enforcement, operation audit | Implements G1–G6 end-to-end |

## Compatibility

### Spec renumbering

- `specs/007-harness-instance-profile-p3.7.md` (renamed from
  `007-harness-instance-profile.md`) is renumbered from P4 to P3.7. Its
  content (instance profile schema) becomes a sub-spec under the P3.x family.
- All references to 007 as "P4" in README and other specs are updated.

### API and CLI stability

Existing API routes (`/agents`, `/sessions`, `/skills`, `/mcp`, `/policy`),
CLI commands (`agentctl`), and SQLite schema remain unchanged. P4 does not
require runtime code changes — it is a goals spec.

### Product language

The product language table from README.md remains authoritative. P4 adds:

| Previous wording | Fleet Control Plane wording |
|------------------|----------------------------|
| Harness Instance Profile (007) | Fleet Instance Profile (P3.7 sub-spec) |
| — | Fleet Health State |
| — | Config Drift Event |
| — | Capacity Budget |
