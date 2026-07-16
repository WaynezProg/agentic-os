# Agent OS / Control Plane / Desktop Reference Research

Date: 2026-07-17

## Research question

Which existing open-source agent OS, agent control-plane, agent IDE, and desktop
projects provide patterns that fit `agentic-os` as a local manager for existing
agent environments?

The research used first-party repositories and official documentation. The
requested background-research agent was unavailable in this environment, so
this is a primary-source review by the main agent rather than an independent
second opinion.

## Bottom line

Do not fork one existing product. Preserve `agentic-os` as a manager rather
than another agent runtime, and combine four proven patterns:

1. Goose for native desktop/session UX, provider setup, keyring-backed
   credentials, extensions, recipes, and an API/ACP boundary.
2. Agno AgentOS for the runtime/control-plane separation and a stable resource
   model for sessions, traces, memory, and connected runtimes.
3. ToolHive and Docker MCP Toolkit for desired-state capability management,
   client connection profiles, lifecycle, isolation, secret injection, and
   verification.
4. OpenHands for typed append-only events and an optional runtime/sandbox
   adapter boundary.

LangGraph Studio and Letta ADE are useful inspection references. AutoGen
Studio, Dify, Flowise, Langflow, Mastra, Agent Zero, and Open WebUI are not good
foundations for this product because they center on building or running agents,
workflow authoring, or chat rather than managing heterogeneous local agent
environments.

## Reference matrix

| Project | What it proves | Use in agentic-os | Do not copy |
|---|---|---|---|
| [Goose](https://github.com/aaif-goose/goose) | A native desktop, CLI, and API can share sessions, providers, extensions, recipes, and credentials. Goose also documents custom distributions and ACP integration. | Session-centric navigation, staged onboarding, provider/auth setup, Keychain UX, streaming, extension status, recipe-style launch templates, API/ACP adapter. | Its own agent loop and provider runtime. `agentic-os` must continue managing Goose-like tools, not become one. |
| [Agno AgentOS](https://docs.agno.com/agent-os/introduction) | A runtime and control plane can be separated while the UI connects directly to a stable API and data remains in the operator's infrastructure. | Connected-runtime resource model, direct local/remote connections, sessions/traces as first-class resources, multi-framework adapter vocabulary. | Cloud-first deployment, multi-user RBAC, and serving agent code inside `agentd`. |
| [ToolHive](https://github.com/stacklok/toolhive) | Registry, runtime, gateway, and portal can form one governed capability lifecycle with local desktop and CLI surfaces. | Capability catalog, install/enable/run/verify states, secret references, policy, client attachment, health checks, and rollbackable desired state. | Kubernetes and mandatory containerization for every local capability. |
| [Docker MCP Gateway](https://github.com/docker/mcp-gateway) | Multiple clients can share one MCP profile while the gateway owns server lifecycle, credentials, OAuth, discovery, logs, and tracing. | MCP profiles, one managed endpoint per environment, OAuth/auth status, runtime health, client connection plan, call-level evidence. | Docker as a required dependency or a single gateway as the only supported execution mode. |
| [OpenHands runtime](https://docs.openhands.dev/openhands/usage/architecture/runtime) and [event model](https://docs.openhands.dev/sdk/arch/events) | Runtime execution can sit behind a client/server contract; immutable typed events can drive state and observers. | Optional sandbox adapter, typed environment/session/change events, durable replayable timelines. | The coding-agent loop, default Docker runtime, and workspace execution ownership. |
| [LangGraph Studio](https://docs.langchain.com/langsmith/studio) | Assistants, threads, and runs are distinct resources; state can be inspected and resumed. | Separate environment definition, persistent conversation/session, and individual execution; expose checkpoints and approval interruptions where upstream supports them. | Graph authoring, hosted LangSmith dependency, and time-travel mutation for tools that cannot support it. |
| [Letta ADE](https://docs.letta.com/guides/ade/overview) | A useful agent IDE exposes the exact prompt, memory, state, tools, and execution rather than only chat output. | Environment inspector with source paths, effective config, overridden values, memory metadata, tools, and live state. | Owning persistent agent memory or rewriting upstream state. |
| [Mastra Studio](https://mastra.ai/studio) | Traces, logs, evals, and HITL can be integrated into one development surface. | Trace presentation and approval UX references. | TypeScript agent framework, workflow engine, eval runtime. |
| [AutoGen Studio](https://github.com/microsoft/autogen/tree/main/python/packages/autogen-studio) | Visual agent/team composition is useful for prototypes. Official docs explicitly say Studio is not production-ready, and AutoGen is now in maintenance mode. | Historical reference only for entity linking and prototype UX. | Dependency, visual workflow builder, or architectural foundation. |
| [Agent Zero](https://github.com/agent0ai/agent-zero) | Project-scoped workspaces can group instructions, memory, secrets, repositories, profiles, and model presets. | Project/environment grouping, backup/restore UX, model presets, explicit host bridge status. | Its Docker agent runtime, desktop-driving agent, memory implementation, and self-modifying behavior. |
| [Open WebUI Desktop](https://github.com/open-webui/desktop) | A desktop can make local/remote connection setup, offline operation, auto-update, and connection switching approachable. | First-run connection UX, connection switcher, update UX, offline/error states. | Chat-first information architecture, embedded inference, Electron dependency, or AGPL code reuse. |
| [Dify](https://github.com/langgenius/dify), [Flowise](https://github.com/FlowiseAI/Flowise), [Langflow](https://github.com/langflow-ai/langflow) | Visual workflow and plugin marketplaces can serve application builders. | Future reference if a separate workflow-authoring product is ever requested. | Current desktop scope. Their central abstraction is an authored workflow/app, not an installed local agent environment. |

## Recommended product boundary

`agentic-os Desktop` should be a **Local Agent Environment Manager**:

- It discovers and identifies CLI, Desktop, IDE extension, background runtime,
  config, auth, capability, and session surfaces separately.
- It records observed state and optional desired state.
- It produces a reviewable reconcile plan before changing anything.
- It delegates installation and upgrade work to the existing system manager
  (Homebrew, mise, application updater, or upstream CLI) through explicit,
  approved actions.
- It launches, resumes, attaches to, observes, and stops sessions only through
  each environment adapter's declared capabilities.
- It never embeds an LLM agent loop, silently edits external state, or claims a
  surface is healthy from a different surface's evidence.

## Proposed architecture

### Environment Adapter

Replace scattered hard-coded tool lists with a versioned adapter manifest and
implementation. Each adapter declares:

- identity and supported surfaces;
- discovery/version/auth/health probes;
- config scopes and safe edit schemas;
- capability readers and writers;
- session discovery, launch, resume, attach, stop, and transcript contracts;
- usage/evidence parsing;
- install, update, reload, and restart action providers;
- validation and verification probes.

An adapter may support only a subset. Unsupported operations remain explicit,
not inferred.

### Environment state

Use one normalized state model:

```text
Environment
  identity
  surfaces[]       CLI / Desktop / IDE / runtime
  auth[]           provider or tool login states
  configs[]        source, scope, effective values, drift
  capabilities[]   skills / MCP / plugins / hooks / memory
  sessions[]       native and agentic-os-managed
  desired_state
  pending_changes[]
  evidence[]
```

Observed state and desired state must remain separate. A stale config folder
does not mean a tool is installed; a CLI version does not prove a Desktop app
or IDE extension loaded the same configuration.

### Reconciliation

All mutations follow:

```text
Observe -> Diff -> Plan -> Approve -> Apply -> Verify -> Record
```

The plan contains exact target surfaces, commands or patch operations,
credential references, restart/reload requirements, rollback availability, and
verification probes. Partial success is represented per surface.

### Desktop information architecture

1. Home — problems requiring attention, active sessions, recent changes.
2. Environments — one row per managed tool/runtime; detail page shows every
   surface and its proof.
3. Sessions — persistent session/thread list with launch, resume, attach,
   transcript, logs, approvals, and evidence.
4. Capabilities — MCP, skills, plugins, hooks, and memory alignment with
   desired-state plans.
5. Changes — pending plans, history, rollback, drift, and verification.
6. Settings — connections, adapter sources, secrets/keyring references,
   updates, diagnostics, and data export.

Chat remains a launcher/view over sessions. It is not the product's primary
navigation or a new agent runtime.

## Desktop completion criteria

The Desktop app is complete for this goal when:

- first launch discovers supported environments and explains every unresolved
  setup step;
- each environment has a cross-surface status page with current evidence;
- the operator can create and apply a safe reconcile plan for supported
  config/capability changes;
- native and managed sessions can be launched or resumed according to adapter
  support, with streaming status, logs, approvals, and evidence;
- auth, health, drift, missing runtime, and reload/restart states are visible;
- local and remote daemon connections have explicit security and degraded
  states;
- keyboard navigation, responsive layouts, empty/loading/error states, and
  accessibility are verified;
- the packaged macOS app starts and stops the daemon reliably, preserves state,
  passes automated tests and product smoke, and produces a release artifact;
- code signing, notarization, and live auto-update are completed when the
  required Apple/update credentials are available, otherwise surfaced as
  external release blockers rather than falsely marked complete.

## Explicit non-goals

- Building another agent runtime, planner, model router, or tool loop.
- A visual multi-agent workflow builder.
- Cloud sync, organization RBAC, or multi-tenant hosting.
- A general-purpose package dependency resolver.
- Mandatory Docker/Kubernetes.
- Pretending every upstream tool supports the same operations.

