# agentic-os

Local Agent Control Plane for managing local coding and orchestration agents.

## P0 Scope

P0 is not a UI, memory system, or Claude OS clone. It is a local daemon and CLI that can reliably start, stop, list, inspect, and log agent sessions.

Read the first spec: [specs/001-daemon-runtime.md](specs/001-daemon-runtime.md).

## Run P0 Locally

Terminal 1:

```bash
uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Terminal 2:

```bash
uv run agentctl agents list
uv run agentctl run shell --cwd "$PWD" --message "OK"
uv run agentctl sessions list
uv run agentctl logs <session_id>
uv run agentctl retry <session_id>
```

Real agent smoke examples:

```bash
uv run agentctl run openclaw --cwd "$PWD" --message "只輸出 OK"
uv run agentctl run hermes --cwd "$PWD" --message "只輸出 OK"
```

Required local smoke is `shell`. Run real agent smoke when OpenClaw or Hermes CLIs are available; if a real agent fails due to its own gateway, auth, model, or CLI state, keep the session id and `agentctl logs <session_id>` output as proof that agentic-os launched it and captured the upstream failure.

2026-05-27 machine verification: `rtk uv run agentctl run openclaw --api http://127.0.0.1:8777 --cwd "$PWD" --message "只輸出 OK"` launched `s_17195fb7386642eca681504d67d92554` and captured OpenClaw's upstream "No target session selected" error; `rtk uv run agentctl run hermes --api http://127.0.0.1:8777 --cwd "$PWD" --message "只輸出 OK"` succeeded as `s_a36fbb159d754b01b069fd8018083b35` with `stdout OK`.

`stop` is only for sessions that are still `running`; the `shell` smoke exits immediately.
For a safe local stop demo, start a daemon with a temporary long-running agent:

```bash
tmp_registry="$(mktemp)"
cat > "$tmp_registry" <<'TOML'
[[agents]]
id = "sleep"
label = "Sleep"
command = ["/bin/sleep", "30"]
cwd_mode = "optional"
stop_policy = "process_group"
TOML
uv run agentd serve --port 8768 --state-dir .agentic-os-stop --registry "$tmp_registry"
```

Then run and stop it from another terminal:

```bash
uv run agentctl run sleep --api http://127.0.0.1:8768 --cwd "$PWD" --message "ignored"
uv run agentctl stop <running_session_id> --api http://127.0.0.1:8768
```

## Run P1 Memory Pipeline

P1 turns a completed session into reviewable local memory:

```text
session logs -> session summary -> review queue -> approved memory -> search
```

Start the daemon:

```bash
rtk uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Run a shell session and promote its summary:

```bash
rtk uv run agentctl run shell --cwd "$PWD" --message "approved memory fact"
rtk uv run agentctl memory summarize <session_id>
rtk uv run agentctl memory review create <session_id>
rtk uv run agentctl memory review list
rtk uv run agentctl memory approve <review_item_id>
rtk uv run agentctl memory search approved
```

Memory promotion is explicit. `review create` queues a deterministic summary;
`approve` creates the durable memory record.

## Run P2 Thin UI

Start the daemon:

```bash
rtk uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Start the no-build static UI:

```bash
cd apps/web
python -m http.server 5173
```

Open `http://127.0.0.1:5173`. The UI defaults to
`http://127.0.0.1:8767`; edit the API URL field if the daemon uses another
port.

P2 shows agents, sessions, bounded logs, memory review/approved memory, and
placeholder Skills/MCP registries. The daemon remains the only process owner.

## Run P3 Skills / MCP / Policy

Start the daemon:

```bash
rtk uv run agentd serve --state-dir .agentic-os --registry examples/agents.toml
```

Use the CLI registry path:

```bash
rtk uv run agentctl skills upsert reviewer --label "Reviewer" --source workspace --tag review
rtk uv run agentctl skills list
rtk uv run agentctl mcp upsert filesystem --label "Filesystem MCP" --transport stdio --env-key MCP_TOKEN
rtk uv run agentctl mcp list
rtk uv run agentctl policy set shell --skill reviewer --mcp filesystem --tool read --model local-model --cwd-root "$PWD"
rtk uv run agentctl policy evaluate shell --skill reviewer --mcp filesystem --tool read --model local-model --cwd "$PWD"
```

Use the daemon API path:

```bash
curl http://127.0.0.1:8767/skills
curl http://127.0.0.1:8767/mcp
curl http://127.0.0.1:8767/policy
```

Use the UI path by starting `apps/web` as in P2 and opening the Skills / MCP tab.
It shows registry rows, policy summary, and deterministic evaluation results.

P3 does not start MCP servers, install skills, execute external tools, enforce
runtime loops, or take over Hermes/OpenClaw. P3 does not execute external tools
during policy evaluation. Secrets must not be stored: use
environment variable names such as `MCP_TOKEN`, not token values. Command and
URL previews are redacted before storage/display.

## P1/P2/P3 Limitations

P1/P2/P3 intentionally do not include:

- LLM-generated summaries; summaries are deterministic from session metadata
  and stdout/stderr logs.
- Embeddings, vector DB, LanceDB, Redis, or remote sync.
- Live policy enforcement inside Hermes/OpenClaw runtime loops.
- MCP server process ownership, browser-side subprocess work, or UI indexing.
- Multi-user auth, RBAC, cloud sync, chat UI, Kanban, Electron, or Tauri.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
```
