# 022 Dashboard Visual System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply CSS design tokens and layout polish to Overview, Runs, and Approvals tabs without adding a build step.

**Architecture:** Refactor `styles.css` with `:root` tokens; add utility classes; update HTML class hooks minimally in `index.html`; JS changes limited to class toggles if needed.

**Tech Stack:** CSS custom properties, vanilla HTML/JS.

---

## File Structure

| File | Changes |
|------|---------|
| `apps/web/styles.css` | Tokens + component classes |
| `apps/web/index.html` | Class hooks on three priority tabs |
| `apps/web/app.js` | Badge/chip class names in render functions |
| `tests/test_web.py` | Ensure tab ids unchanged |
| `specs/017-harness-dashboard-v2.md` | Visual gap closed note |
| `specs/022-dashboard-visual-system.md` | Status → Implemented |

---

### Task 1: Design tokens foundation

**Files:**
- Modify: `apps/web/styles.css`

- [ ] **Step 1: Add :root token block from spec 022**

- [ ] **Step 2: Replace hard-coded colors in body, nav, table with var() references**

Search `#` hex in styles.css and migrate top 20 occurrences.

- [ ] **Step 3: Visual check**

Open `http://127.0.0.1:5173` — no broken layout.

- [ ] **Step 4: Commit**

```bash
git add apps/web/styles.css
git commit -m "feat(ui): add design tokens to dashboard CSS"
```

---

### Task 2: Shared component classes

**Files:**
- Modify: `apps/web/styles.css`, `apps/web/index.html`

- [ ] **Step 1: Add .card, .badge, .timeline-entry, .table-compact, .btn-primary, .btn-danger**

- [ ] **Step 2: Apply .table-compact to all `<table>` elements**

- [ ] **Step 3: Commit**

---

### Task 3: Overview tab polish

**Files:**
- Modify: `apps/web/index.html`, `apps/web/app.js`, `styles.css`

- [ ] **Step 1: Wrap overview metrics in .card grid**

Update `loadOverview()` to emit card structure.

- [ ] **Step 2: Status chips use .badge --success/--warning/--danger**

- [ ] **Step 3: Commit**

---

### Task 4: Runs tab split pane

**Files:**
- Modify: `styles.css`, `index.html`

- [ ] **Step 1: CSS grid/flex split 35/65 for session list + timeline**

```css
.runs-layout {
  display: grid;
  grid-template-columns: 35% 65%;
  gap: var(--space-md);
}
@media (max-width: 900px) {
  .runs-layout { grid-template-columns: 1fr; }
}
```

- [ ] **Step 2: Wrap Runs tab content in .runs-layout**

- [ ] **Step 3: Style .timeline-entry with left border per type**

- [ ] **Step 4: Commit**

---

### Task 5: Approvals tab polish

**Files:**
- Modify: `apps/web/app.js`, `styles.css`

- [ ] **Step 1: Approve/reject buttons → .btn-primary / .btn-danger**

- [ ] **Step 2: Status column → .badge variants**

- [ ] **Step 3: Commit**

---

### Task 6: Verification

- [ ] **Step 1: Run web tests**

Run: `rtk uv run pytest tests/test_web.py -q`
Expected: PASS

- [ ] **Step 2: Confirm no package.json in apps/web**

Run: `test ! -f apps/web/package.json`

- [ ] **Step 3: Update specs 017/022 status**

- [ ] **Step 4: Commit**

```bash
git add apps/web/ specs/017-harness-dashboard-v2.md specs/022-dashboard-visual-system.md
git commit -m "feat(ui): dashboard visual system for Overview/Runs/Approvals"
```

---

## Self-Review

- [ ] Tokens in :root
- [ ] Three priority screens polished
- [ ] No build tooling added
- [ ] test_web.py passes
