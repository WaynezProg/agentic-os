# 046 — Desktop Product Polish (P27)

Status: Draft
Date: 2026-06-07
Depends on: desktop app shell (`specs/028-desktop-app-shell.md`), packaged macOS app (`specs/029-packaged-macos-app.md`), SLO/diagnostics (`specs/010-slo-benchmark-harness.md`), bounded log reads (P6, `specs/014-evidence-audit-timeline.md`)
Blocks: —

## Positioning

Make the `.app` usable day-to-day: first-run wizard, health diagnostics, broken-config
repair, logs download, version info, and an update-check **placeholder** (no auto-update
infrastructure).

## Scope

| Owns | Does not own |
|------|--------------|
| First-run wizard, health diagnostics view (reuse P8 diagnostics) | Hosted telemetry / continuous monitoring |
| Broken-config repair via `safe_edit_engine` + backup | Auto-update delivery infra |
| Logs download (bounded reads, redacted), version info, update-check placeholder | Package management |

## Acceptance criteria

| Criterion | Verification |
|-----------|--------------|
| First-run wizard guides registry + profile setup | manual |
| Diagnostics surfaces health/resource snapshot (P8) | `tests/test_*diagnostics*` |
| Config repair uses safe-edit + backup (no ad-hoc writes) | code review |
| Logs download respects bounded reads + redaction | unit |

## Conflicts & resolutions

- **Repair can corrupt what it fixes** — ad-hoc writes during "repair" are the worst place to skip
  safety. **→ Resolution**: repair generates a `SafeEditEngine` dry-run patch, shows the diff, and
  applies with a snapshot/backup and `/patches/{id}/rollback` — never a direct file write. A repair
  that can't be expressed as a validated patch is surfaced as a manual step, not auto-applied.
- **Update check overreach** — a background updater would add a process owner (CLAUDE.md forbids).
  **→ Resolution**: ship a static version display plus a manual "check" that hits a version endpoint
  or is a no-op stub; no daemon, no auto-download.
- **Logs download leakage** — **→ Resolution**: stream through the P6 bounded-read path with
  `_redact_value` applied before bytes leave the daemon; package server-side as a zip so redaction
  can't be skipped client-side.
