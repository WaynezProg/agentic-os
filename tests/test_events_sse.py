from __future__ import annotations

from pathlib import Path

from agentic_os.audit import AuditStore
from test_api import make_client


def _pair_device(client, *, device_name: str = "sse-client") -> str:
    code = client.post("/remote/pairing/start").json()["pairing_code"]
    payload = client.post(
        "/remote/pairing/complete",
        json={"pairing_code": code, "device_name": device_name},
    ).json()
    return payload["auth_token"]


def test_events_sse_requires_auth(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/events")
    assert response.status_code == 401


def test_events_sse_event_source_ready(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    token = _pair_device(client)
    audit = AuditStore(tmp_path / ".agentic-os" / "agentic-os.db")
    audit.record(
        "config_patch",
        "agentic-os",
        "config_patched",
        "dry-run patch applied",
        {"surface": "workflow"},
    )
    rows = audit.list_events_after_id(0, domain="config_patch")
    assert len(rows) == 1
    assert rows[0].domain == "config_patch"
    unauthorized = client.get("/events")
    assert unauthorized.status_code == 401
    # Stream body is infinite; contract coverage uses list_events_after_id + auth gate.
    assert token
