from __future__ import annotations

from pathlib import Path

import typer
import uvicorn

from agentic_os.api import create_app


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
    api = create_app(state_dir=state_dir, registry_path=registry)
    uvicorn.run(api, host=host, port=port)
