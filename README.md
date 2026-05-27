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
uv run agentctl stop <session_id>
```

Real agent smoke examples:

```bash
uv run agentctl run openclaw --cwd "$PWD" --message "只輸出 OK"
uv run agentctl run hermes --cwd "$PWD" --message "只輸出 OK"
```

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
```
