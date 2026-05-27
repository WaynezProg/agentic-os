# agentic-os

Local Agent Control Plane for managing local coding and orchestration agents.

## P0 Scope

P0 is not a UI, memory system, or Claude OS clone. It is a local daemon and CLI that can reliably start, stop, list, inspect, and log agent sessions.

Core commands:

```bash
agentctl agents list
agentctl run openclaw --cwd ~/Projects/demo
agentctl sessions list
agentctl logs <session_id>
agentctl stop <session_id>
```

Read the first spec: [specs/001-daemon-runtime.md](specs/001-daemon-runtime.md).

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
```
