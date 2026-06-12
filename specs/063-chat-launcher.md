# 063 — P43 Chat Launcher

Status: implemented (main)

## Problem

Launching a harness run today means a form: pick an instance, fill cwd,
type a message, press 執行, then go find the logs. The daily mental model
the operator actually has is conversational — "把這句話丟給 codex" — and
the manager already owns everything needed (policy-gated `POST /sessions`,
log store, status lifecycle). What is missing is only the chat-shaped
presentation of that existing run path.

## Owns

- `apps/web/ui/chat-launcher.js` — 聊天 tab UI:
  - composer (harness select + message textarea + Enter-to-send) feeding
    the existing `POST /sessions` gate; workspace selection supplies cwd.
  - one chat turn == one managed session. The user bubble is the message;
    the tool reply bubble is a **bounded preview** of that session's
    stdout (stderr appended on failure) with a live status chip polled
    until terminal. Bounds: `max_lines` on the fetch plus client-side
    line/char caps with an explicit truncation marker; localStorage only
    ever holds the capped preview. Full output stays in the log view.
  - policy `deny` / `approval_required` render as system bubbles carrying
    decision + reason + shadow `session_id`, linking to session logs.
  - thread history persists client-side only (localStorage, capped),
    with per-bubble jump links into the 執行 tab log view.
- 聊天 tab in the 日常使用 nav group (`tab-chat`, `panel-chat`).
- Sidebar orientation sublabels (`.tab-desc`) on every nav tab.

## Does not own

- No new daemon endpoints, no LLM calls, no message routing/intent
  parsing — the typed message goes verbatim to the chosen harness's
  `{{message}}` template via the existing run path.
- No multi-turn conversation state inside one harness process (each send
  is a fresh one-shot run; resume/attach stays with P36/P39 surfaces).
- No streaming transport; the reply view is the existing poll-based log
  read.
- No server-side chat history (sessions remain the durable record).

## Interaction contract

1. send → `POST /sessions {agent_id, message, cwd?}`.
2. HTTP 403/409 → system bubble with `decision/reason/session_id`; no
   user-facing dead end (audit link preserved).
3. accepted → tool bubble polls `GET /sessions/{id}` every 1.5s until
   `succeeded|failed|stopped`, then renders a bounded stdout preview from
   `GET /sessions/{id}/logs?max_lines=…` (client caps lines/chars and
   marks truncation).
4. 清除歷史 wipes only the local thread; session records and evidence
   stay under the 執行 tab.
