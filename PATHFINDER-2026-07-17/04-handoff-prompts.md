# Pathfinder Handoff Prompts

These prompts are retained as subsystem planning boundaries. The approved goal
uses equivalent detailed plans under `docs/superpowers/plans/`.

## Environment, probe, and native sessions

```text
/make-plan Implement the unified Environment system from
PATHFINDER-2026-07-17/03-unified-proposal.md.

Single entry points:
- EnvironmentService.observe()
- ProbeService.probe()
- NativeSessionService.scan()

Rewrite the call sites identified in:
- 01-flowcharts/environment-inventory.md
- 01-flowcharts/session-lifecycle.md
- 02-duplication-report.md sections 2, 3, and 5

Preserve every existing API response and bounded-IO invariant while adding
/environments and /environments/{id}. Use a static built-in adapter table; do
not create dynamic plugin discovery, a factory hierarchy, or a second registry
file. Keep tool-specific parsers specialized.
```

## Change lifecycle

```text
/make-plan Implement ChangeService from
PATHFINDER-2026-07-17/03-unified-proposal.md.

Single entry points:
- ChangeService.preview()
- ChangeService.apply()
- ChangeService.rollback()

Rewrite supported file/config mutation call sites from:
- 01-flowcharts/change-reconciliation.md
- 02-duplication-report.md sections 1 and 7

Keep SafeEditEngine as the only file writer. Add durable plan state and
post-apply/post-rollback re-observation. Do not invent a generic mutation DSL,
replace relational control-plane history, or silently auto-apply a plan.
```

## Desktop transport and navigation

```text
/make-plan Implement the Desktop transport and six-area operator shell from
PATHFINDER-2026-07-17/03-unified-proposal.md.

Single entry points:
- connection::api_request()
- AgenticOs.Navigation.show()

Rewrite call sites from:
- 01-flowcharts/desktop-connection-shell.md
- 02-duplication-report.md sections 4 and 8

Support GET/POST/PUT/PATCH/DELETE in local and remote profiles. Keep remote
tokens in Keychain. Use authenticated polling through the Rust bridge for the
Web approval/event stream. Reuse existing panels as subviews and remove the
15-item top-level navigation; do not add React, a bundler, or a legacy-nav
feature flag.
```

## Release verification

```text
/make-plan Verify the complete Local Agent Environment Manager Desktop goal.

Cover Python API/domain tests, JS syntax and DOM tests, Rust unit tests,
product/remote/Desktop smokes, a release Tauri build, app launch/quit/relaunch,
listener cleanup, screenshots at desktop and narrow widths, keyboard focus,
loading/empty/error states, and package artifact inspection.

Treat signing, notarization, and live updater publication as complete only when
the required Apple and update-channel credentials are present and exercised.
Otherwise record exact external blockers without claiming a production-signed
release.
```

