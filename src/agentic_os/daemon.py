from __future__ import annotations

import os
from pathlib import Path

import typer
import uvicorn

from agentic_os.api import create_app

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


app = typer.Typer(help="Run the agentic-os daemon.")


@app.callback()
def main() -> None:
    pass


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(8767, "--port", help="Bind port."),
    state_dir: Path = typer.Option(
        Path(".agentic-os"),
        "--state-dir",
        help="Runtime state directory.",
    ),
    registry: Path = typer.Option(
        Path("examples/agents.toml"),
        "--registry",
        help="Agent registry TOML.",
    ),
) -> None:
    if host not in _LOOPBACK and os.environ.get("AGENTIC_OS_ALLOW_PUBLIC_BIND") != "1":
        raise typer.BadParameter(
            "agentd must bind loopback only (127.0.0.1); use a remote gateway for external access."
        )
    api = create_app(state_dir=state_dir, registry_path=registry)
    uvicorn.run(api, host=host, port=port)
