# 061 — P41 Transcript Preview

Status: implemented (branch `feat/p34-p38-dual-track-product`)
Design: `docs/superpowers/specs/2026-06-12-capability-radar-design.md`

## Problem

The P39 radar lists real sessions but the operator could not see what a
session talked about without leaving the app. Conversation visibility is
the minimum for "manage dialogues".

## Owns

- `live_sessions.read_transcript_tail(path, tool, limit)`: tail-bounded
  (256KB seek window, first partial line dropped) parse of the last
  user/assistant messages. Claude: `type` user/assistant with
  `message.content` text. Codex: `event_msg` `user_message`/`agent_message`
  (`response_item` duplicates are intentionally ignored). Noise filtered via
  the shared real-prompt heuristics; per-message text clipped to 2000 chars.
- `GET /sessions/live/transcript?tool=&log_path=&limit=`:
  - `log_path` must resolve under a configured live-session root and end in
    `.jsonl`, otherwise 400 — prevents arbitrary file reads.
  - `limit` clamps to [1, 200], default 50; returns `{messages, count, tool}`.
- Dashboard radar UI: clicking a session title toggles an inline transcript
  panel (last 20 messages, chat-style 你/AI rows, loading + error states).

## Does not own

- Sending messages into sessions, resuming, or any write to transcripts.
- Full-transcript pagination/search; this is a tail preview.
- Tools beyond claude/codex (extension point mirrors `_SCANNERS`).
