# Repository Guidelines

## Project Structure & Module Organization

`agentic-os` is a local Harness Manager substrate. Core Python code lives in `src/agentic_os/`: `api.py` owns FastAPI routes, `cli.py` owns Typer commands, `storage.py` and `memory_store.py` own SQLite persistence, and `supervisor.py` owns subprocess lifecycle. Tests live in `tests/` and mirror module names, with end-to-end coverage in `test_end_to_end.py`. The static no-build UI is `apps/web/index.html`, `apps/web/app.js`, and `apps/web/styles.css`. Phase contracts live in `specs/`; implementation plans live in `docs/superpowers/plans/`. Example harness registry data is in `examples/agents.toml`.

## Build, Test, and Development Commands

- `rtk uv sync`: install Python 3.12 dependencies from `pyproject.toml` and `uv.lock`.
- `rtk uv run pytest -q`: run the full pytest suite.
- `rtk uv run pytest tests/test_api.py -q`: run one test file during focused work.
- `rtk uv run ruff check .`: run lint checks.
- `rtk uv run ruff format .`: format Python files.
- `rtk bash scripts/start-local.sh`: start `agentd` on `127.0.0.1:8767` and the static UI on `127.0.0.1:5173`.

## Coding Style & Naming Conventions

Use Python 3.12, 4-space indentation, type hints where interfaces cross modules, and Ruff defaults with `line-length = 100`. Keep the daemon as the only process owner; CLI and web code should remain thin HTTP clients. Name tests `test_<module>.py` and test functions `test_<behavior>`. Keep product language as Harness Manager / Harness Run / Shared Capability Catalog, while preserving existing API and CLI labels such as `/agents`, `/sessions`, `agentctl agents`, and `agentctl sessions`.

## Testing Guidelines

Add or update tests with behavior changes. API changes need request/response coverage in `tests/test_api.py`; CLI changes need coverage in `tests/test_cli.py`; supervisor changes must keep subprocess commands fast and self-terminating. Before handing off code, run:

```bash
rtk uv run pytest -q && rtk uv run ruff check .
```

## Commit & Pull Request Guidelines

Recent history uses concise imperative subjects, often Conventional Commit prefixes: `feat: ...`, `fix: ...`, `docs: ...`, plus occasional direct subjects like `Implement policy-aware session runs`. PRs should describe behavior changes, list verification commands, link relevant specs or issues, and include UI screenshots when `apps/web/` changes.

## Security & Configuration Tips

Runtime state belongs under `.agentic-os/` and is ignored. Do not commit local state, logs, artifacts, or secrets. Skills/MCP configuration must store environment variable names such as `MCP_TOKEN`, never secret values. Keep redaction behavior in `control_plane.py` intact when adding policy or catalog fields.
