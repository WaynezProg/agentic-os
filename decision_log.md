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

