from __future__ import annotations

from typer.testing import CliRunner

from agentic_os.daemon import app


runner = CliRunner()


def test_serve_rejects_public_bind() -> None:
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0"])
    assert result.exit_code != 0
    assert "127.0.0.1" in result.output
