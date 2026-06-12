from __future__ import annotations

import io
import zipfile
from pathlib import Path

from test_api import make_client


def test_diagnostics_resources_snapshot(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/diagnostics/resources")
    assert response.status_code == 200
    body = response.json()
    for key in ("session_count", "audit_event_count", "fleet_event_count"):
        assert key in body


def test_version_endpoint_is_stub(tmp_path: Path) -> None:
    from agentic_os import __version__

    client = make_client(tmp_path)
    response = client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == __version__
    assert body["update_check"] == "stub"
    assert body["update_available"] is False


def test_setup_logs_zip_is_bounded_and_redacted(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    run = client.post(
        "/sessions",
        json={"agent_id": "shell", "cwd": str(tmp_path), "message": "logzip"},
    )
    assert run.status_code == 200
    response = client.get("/setup/logs.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    assert names
    sample = archive.read(names[0]).decode("utf-8")
    assert "SECRET_SHOULD_NOT_APPEAR" not in sample
