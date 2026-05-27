from pathlib import Path

from typer.testing import CliRunner

import agentic_os.daemon as daemon
from agentic_os.daemon import app


def test_agentd_help_mentions_serve_command() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "serve" in result.output


def test_agentd_serve_runs_api_with_configured_options(monkeypatch) -> None:
    api = object()
    calls: dict[str, object] = {}

    def fake_create_app(*, state_dir: Path, registry_path: Path) -> object:
        calls["state_dir"] = state_dir
        calls["registry_path"] = registry_path
        return api

    def fake_run(received_api: object, *, host: str, port: int) -> None:
        calls["api"] = received_api
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr(daemon, "create_app", fake_create_app)
    monkeypatch.setattr(daemon.uvicorn, "run", fake_run)

    result = CliRunner().invoke(
        app,
        [
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "9999",
            "--state-dir",
            "tmp/state",
            "--registry",
            "tmp/agents.toml",
        ],
    )

    assert result.exit_code == 0
    assert calls == {
        "state_dir": Path("tmp/state"),
        "registry_path": Path("tmp/agents.toml"),
        "api": api,
        "host": "0.0.0.0",
        "port": 9999,
    }
