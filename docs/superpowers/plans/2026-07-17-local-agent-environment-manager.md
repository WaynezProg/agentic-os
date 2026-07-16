# Local Agent Environment Manager Implementation Index

**Goal:** Turn agentic-os into a daily-usable macOS Desktop manager for local
agent environments without turning the daemon into another agent runtime.

**Design:** [Local Agent Environment Manager design](../specs/2026-07-17-local-agent-environment-manager-design.md)

## Delivery plans

1. [Environment foundation](2026-07-17-environment-foundation.md) — built-in
   adapters, normalized six-surface observation, shared probes, native sessions,
   and launch decisions.
2. [Verified Change lifecycle](2026-07-17-change-lifecycle.md) — durable
   preview/apply/re-observe/rollback plans over `SafeEditEngine`.
3. [Desktop transport](2026-07-17-desktop-transport.md) — local/remote Tauri
   bridge, Keychain bearer boundary, events polling, startup state, and CSP.
4. [Desktop operator experience](2026-07-17-desktop-operator-experience.md) —
   Home, Environments, Sessions, Capabilities, Changes, and Settings.

## Completion contract

- The four delivery plans above are implemented.
- Product smoke covers environment inventory and a Change round trip.
- Rust and Web transport tests cover structured local/remote HTTP errors.
- A packaged arm64 `.app` passes launch, tray Quit, crash-orphan recovery,
  remote transport, and strict codesign verification both before and after
  running its bundled daemon.
- Developer ID signing, notarization, DMG publication, updater delivery, and
  non-arm64/non-macOS packages remain external release work.
