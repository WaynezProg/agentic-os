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

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
```
