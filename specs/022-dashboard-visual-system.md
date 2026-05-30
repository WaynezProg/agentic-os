# 022 — Dashboard Visual System

Status: Implemented
Date: 2026-05-30
Depends on: 017 (tab structure frozen), 021 (Runs/Logs IA)
Parallel with: 020 completion optional (Harnesses tab native config panel from 020 is nice-to-have for 022)
Blocks: 023 (visual consistency)

## Positioning

Apply a cohesive design system to the static web UI. **No build step** — CSS
custom properties + refactored `styles.css` only. Open Design artifacts may
inform tokens but are not runtime dependencies.

| Phase | Owns | Does not own |
|-------|------|--------------|
| P9+ visual | design tokens, layout, three priority screens | chat, Kanban, terminal multiplexer |

## Build strategy (locked)

- Plain HTML + CSS + JS
- No Vite, no npm, no bundler
- All tokens in `:root { --... }` in `styles.css`

## Design tokens

```css
:root {
  --color-bg: #0f1117;
  --color-surface: #1a1d27;
  --color-border: #2a2f3a;
  --color-text: #e6e8ef;
  --color-text-muted: #8b919e;
  --color-accent: #5b8def;
  --color-success: #3dd68c;
  --color-warning: #f5a524;
  --color-danger: #f04438;
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --radius-sm: 4px;
  --radius-md: 8px;
  --font-mono: ui-monospace, "SF Mono", monospace;
  --font-sans: system-ui, -apple-system, sans-serif;
}
```

Adjust values during implementation; structure is fixed.

## Priority screens (implementation order)

### 1. Overview

- Card grid: fleet health summary, running sessions count, pending approvals
- Status chips use token colors
- Empty states with muted text

### 2. Runs (Sessions + Timeline from 021)

- Split pane: session list (left 35%) / timeline + logs (right 65%)
- Timeline entry cards with type-specific left border color
- Responsive: stack vertically below 900px width

### 3. Approvals

- Queue table with status badges
- Approve/reject buttons use accent/danger tokens
- Linked session id as button → Runs tab navigation (021)

## Shared components (CSS classes)

| Class | Use |
|-------|-----|
| `.card` | Overview metrics, harness panels |
| `.badge` | status, harness type |
| `.timeline-entry` | 021 timeline rows |
| `.table-compact` | all data tables |
| `.btn-primary` / `.btn-danger` | actions |

## Tab freeze

Do **not** add Projects, Diagnostics, Chat, or Kanban tabs. Existing 11 tabs
keep ids; only visual treatment changes.

## Does not own

- New API endpoints
- New functional tabs
- Build tooling
- Dark/light theme toggle (dark only in 022)

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| Tokens defined in `:root` | CSS review |
| Overview/Runs/Approvals visually consistent | manual screenshot |
| No npm/package.json added under `apps/web/` | file check |
| `test_web.py` still passes | CI |
| Mobile-width layout stacks Runs pane | manual 375px |
| 017 "Implemented with gaps" → visual gap closed | spec update |

## Implementation plan

`docs/superpowers/plans/2026-05-30-022-dashboard-visual-system.md`
