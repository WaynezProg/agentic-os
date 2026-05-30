# Spec Debt Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze 001–017 spec statuses to match implemented code; mark duplicate specs superseded; add README rows for 018–023 without implementing them.

**Architecture:** Documentation-only PR. No runtime behavior changes. Each spec file gets Status + Implementation Status sections aligned with test coverage.

**Tech Stack:** Markdown, README phase table.

---

## File Structure

| File | Action |
|------|--------|
| `specs/001-daemon-runtime.md` … `006-*.md` | Status → Implemented |
| `specs/007-harness-instance-profile-p3.7.md` | Status → Implemented via 018; note schema in code |
| `specs/008-*.md`, `009`, `010`, `011` | Align status to code reality |
| `specs/012-workflow-surface-catalog.md` | Status → Superseded by 014 |
| `specs/014-evidence-audit-timeline.md` | Status → Superseded by 015 |
| `specs/015-approval-queue.md` | Status → Superseded by 016 |
| `specs/016-harness-dashboard-v2.md` | Status → Superseded by 017 |
| `README.md` | Add 018–023 phase rows (Planned) |
| `docs/superpowers/specs/2026-05-30-spec-schedule-018-plus-design.md` | Already written |

---

### Task 1: Freeze P0–P3.6 specs (001–006)

**Files:**
- Modify: `specs/001-daemon-runtime.md`, `002`, `003`, `004`, `005`, `006`

- [ ] **Step 1: Update Status line in each file**

Change `Status: Draft` (or `Awaiting written spec review`) to:

```markdown
Status: Implemented
```

- [ ] **Step 2: Append Implementation Status section to 001**

```markdown
## Implementation Status

Implemented in `src/agentic_os/daemon.py`, `api.py`, `cli.py`, `supervisor.py`,
`storage.py`, `logs.py`. Verified by `tests/test_api.py`, `test_supervisor.py`,
`test_storage.py`, `test_end_to_end.py`.
```

Repeat equivalent pointer for 002–006 referencing matching test files.

- [ ] **Step 3: Verify no scope additions**

Do not add new requirements — status documentation only.

- [ ] **Step 4: Commit**

```bash
git add specs/00{1,2,3,4,5,6}*.md
git commit -m "docs: mark P0-P3.6 specs as Implemented"
```

---

### Task 2: Annotate 007 (status change deferred to 018 PR)

**Files:**
- Modify: `specs/007-harness-instance-profile-p3.7.md`

- [ ] **Step 1: Keep Status as Draft; add schedule pointer only**

Do **not** set `Implemented via 018` here — that happens in the 018 implementation PR
when registry data lands.

```markdown
Status: Draft

> Schema implemented in code (`AgentDefinition`, `_harness_profile()`).
> Status → Implemented via 018 when `examples/agents.toml` is complete.
> See `specs/018-multi-harness-registry-pack.md`.
```

- [ ] **Step 2: Fix canonical id example**

Replace `openclaw@work` in field description with:

```markdown
- `id`: stable path-safe id, for example `openclaw` (see 018 for canonical ids).
```

- [ ] **Step 3: Commit**

```bash
git add specs/007-harness-instance-profile-p3.7.md
git commit -m "docs: annotate 007 pending 018 registry data"
```

---

### Task 3: Supersede duplicate specs

**Files:**
- Modify: `specs/012-workflow-surface-catalog.md`
- Modify: `specs/014-evidence-audit-timeline.md`
- Modify: `specs/015-approval-queue.md`
- Modify: `specs/016-harness-dashboard-v2.md`

- [ ] **Step 1: Add superseded banner to each duplicate**

```markdown
Status: Superseded

> Superseded by `specs/014-workflow-surface-catalog.md`. Do not implement.
```

(use 015, 016, 017 respectively for other files)

- [ ] **Step 2: Commit**

```bash
git add specs/012-workflow-surface-catalog.md specs/014-evidence-audit-timeline.md specs/015-approval-queue.md specs/016-harness-dashboard-v2.md
git commit -m "docs: mark duplicate specs superseded"
```

---

### Task 4: README phase table — add 018–023

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append rows after P9+ dashboard row**

```markdown
| P10+ | multi-harness registry pack | six harness instances with full profiles | registry validation, fleet probe coverage | resume, PTY, config writes |
| P10++ | workflow catalog expansion | six-harness surface scan | catalog scopes, merged/diff UI | executing surfaces |
| P11+ | harness config bridge | read harness-native configs | effective/diff/explain per harness | config writes, 013 overlap |
| P11++ | session timeline UX | timeline-first Runs/Logs | log_chunk, pagination, approval links | live streaming |
| P12+ | dashboard visual system | design tokens, Overview/Runs/Approvals polish | CSS-only visual system | build step, new tabs |
| P12++ | session attach contract (gated) | attach preview/exec contract | external_session_id, harness matrix | PTY UI |
```

Naming follows existing `P5+` / `P6+` style (`++` = second tranche at same layer).

- [ ] **Step 2: Add spec links paragraph**

```markdown
Planned specs: [018](specs/018-multi-harness-registry-pack.md) → [023](specs/023-session-attach-contract.md). Schedule: [design doc](docs/superpowers/specs/2026-05-30-spec-schedule-018-plus-design.md).
```

- [ ] **Step 3: Run web test if README assertions exist**

Run: `rtk uv run pytest tests/test_web.py -q`
Expected: PASS (update test if it asserts exact phase row count)

- [ ] **Step 4: Commit**

```bash
git add README.md tests/test_web.py
git commit -m "docs: add 018-023 planned phases to README"
```

---

## Self-Review

- [ ] All 001–006 show Implemented
- [ ] 007 points to 018 for data
- [ ] Four duplicates show Superseded
- [ ] README links to new specs
- [ ] No Python source files changed
