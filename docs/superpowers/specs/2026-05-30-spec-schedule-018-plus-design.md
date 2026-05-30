# Spec Schedule 018+ Design

Date: 2026-05-30
Status: Draft — review applied 2026-05-30 (planning only, no implementation)

## Summary

Close spec debt on 001–017 (freeze status, no scope expansion), then ship
018–023 in strict dependency order. One spec per PR; each PR updates README
phase table and spec status.

## Decisions (locked)

### Harness instance ID convention

**Canonical id = short catalog key, 1:1 with `_HARNESS_SCOPES`:**

`claude`, `codex`, `opencode`, `qwen`, `openclaw`, `hermes`

- Registry `agents.toml` `id` matches catalog harness key exactly.
- 007 example `openclaw@work` is illustrative only; multi-instance same-type
  uses suffix: `openclaw`, `openclaw@work` (future), but catalog key stays
  `openclaw` via explicit `catalog_harness` field only if needed later — **not
  in 018** (single instance per type in `examples/agents.toml`).

### TOML field mapping (007 → registry)

| 007 spec field | `agents.toml` / `AgentDefinition` field |
|----------------|----------------------------------------|
| `id` | `id` |
| `name` | `label` |
| `launch_command` | `command` |
| `health_command` | `health_command` |
| `attach_command` | `attach_command` |
| `config_path` | `config_path` |
| `workspace_roots` | `workspace_roots` |
| `log_paths` | `log_paths` |
| `default_provider` | `default_provider` |

Fleet extras already in code (not 007): `version_command`,
`config_fingerprint_command`, `enabled`.

### Duplicate spec numbering

Do **not** renumber. Mark superseded duplicates; keep canonical files:

| Canonical | Superseded duplicate | Action |
|-----------|---------------------|--------|
| `014-workflow-surface-catalog.md` | `012-workflow-surface-catalog.md` | Status → Superseded by 014 |
| `015-evidence-audit-timeline.md` | `014-evidence-audit-timeline.md` | Status → Superseded by 015 |
| `016-approval-queue.md` | `015-approval-queue.md` | Status → Superseded by 016 |
| `017-harness-dashboard-v2.md` | `016-harness-dashboard-v2.md` | Status → Superseded by 017 |

### UI build strategy (022)

**No build step.** Plain `index.html` + `styles.css` + `app.js` only. Design
tokens live in CSS custom properties. No Vite, no npm in 022.

### 023 optional gate

Write spec 023 only after 018–022 acceptance criteria pass manual smoke on
Wayne's machine. Until then: spec file exists as `Status: Gate — do not
implement`.

## Spec debt closure (before 018)

| Spec | Phase | Current status | Action |
|------|-------|----------------|--------|
| 001–006 | P0–P3.6 | Draft / Awaiting review | → `Implemented`; add Implementation Status pointing at tests; **no new scope** |
| 007 | P3.7 | Draft | → `Implemented via 018` in **018 PR** (not spec-debt PR) |
| 008–011 | P4–P9 goals | Draft / Planned | → `Implemented` or `Implemented with gaps` per code reality; no expansion |
| 013 | P5+ config | Implemented | Maintain only |
| 014 | P6+ surfaces | Implemented with gaps | Gap closure → **019**, not 014 |
| 015 | P7+ timeline | Implemented with gaps | Gap closure → **021**, not 015 |
| 016 | P8+ approvals | Implemented with gaps | Minor gap closure in **021** UI only |
| 017 | P9+ dashboard | Implemented with gaps | Tab freeze; visual → **022** |

## New spec dependency chain

```
007 (schema in code; status frozen in spec-debt PR)
  └─► 018 Multi-Harness Registry Pack
        └─► 019 Workflow Catalog Expansion
              ├─► 020 Harness Config Bridge (read-only)  ─┐
              └─► 021 Session & Harness Timeline UX       ├─ parallel after 019
                          └─► 022 Dashboard Visual System ◄┘ (needs 021 IA; 020 optional)
                                └─► 023 Session Attach Contract (optional gate)
```

**Order rule:** 018 → 019 is mandatory. **020 and 021 may run in parallel** after
019. 022 needs 021 IA complete (020 not blocking). 023 blocked until 018–022
smoke passes.

## Out of scope (unless product thesis changes)

| Topic | Reason |
|-------|--------|
| Semantic KB / RAG / embedding | P1/P9 non-goals |
| Kanban / spec board | Not Harness Manager |
| MCP server lifecycle | P3 explicit non-goal |
| In-harness tool approval | P7 non-goal |
| Multi-pane terminal UI | New product line |

## Deliverables map

| Artifact | Path |
|----------|------|
| This design | `docs/superpowers/specs/2026-05-30-spec-schedule-018-plus-design.md` |
| Spec debt plan | `docs/superpowers/plans/2026-05-30-spec-debt-closure.md` |
| 018 spec | `specs/018-multi-harness-registry-pack.md` |
| 019 spec | `specs/019-workflow-catalog-expansion.md` |
| 020 spec | `specs/020-harness-config-bridge.md` |
| 021 spec | `specs/021-session-harness-timeline-ux.md` |
| 022 spec | `specs/022-dashboard-visual-system.md` |
| 023 spec | `specs/023-session-attach-contract.md` |
| Implementation plans | `docs/superpowers/plans/2026-05-30-018-*.md` … `023-*.md` |

## PR sequence

1. Spec debt closure (status-only + README)
2. 018 — registry pack
3. 019 — catalog expansion
4. 020 — harness config bridge
5. 021 — timeline UX
6. 022 — visual system
7. 023 — attach contract (after gate)
