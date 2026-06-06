from __future__ import annotations

from pathlib import Path

import pytest

from agentic_os.remote_access import RemoteAccessError, RemoteAccessService
from test_api import make_client


def test_pairing_start_and_complete(tmp_path: Path) -> None:
    svc = RemoteAccessService(tmp_path / ".agentic-os")
    started = svc.start_pairing(ttl_seconds=300)
    assert len(started["pairing_code"]) == 6
    completed = svc.complete_pairing(
        pairing_code=started["pairing_code"],
        device_name="iphone-test",
    )
    assert completed["device_id"]
    assert completed["auth_token"]
    assert svc.validate_token(completed["auth_token"]) == completed["device_id"]


def test_pairing_rejects_invalid_code(tmp_path: Path) -> None:
    svc = RemoteAccessService(tmp_path / ".agentic-os")
    with pytest.raises(RemoteAccessError):
        svc.complete_pairing(pairing_code="000000", device_name="bad")


def test_pairing_api_flow(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    start = client.post("/remote/pairing/start")
    assert start.status_code == 200
    code = start.json()["pairing_code"]
    done = client.post(
        "/remote/pairing/complete",
        json={"pairing_code": code, "device_name": "test-device"},
    )
    assert done.status_code == 200
    token = done.json()["auth_token"]
    device_id = done.json()["device_id"]
    devices = client.get("/remote/devices")
    assert devices.status_code == 200
    assert len(devices.json()["devices"]) == 1
    revoke = client.delete(f"/remote/devices/{device_id}")
    assert revoke.status_code == 200
    events = client.get("/events", headers={"Authorization": f"Bearer {token}"})
    assert events.status_code == 401


def test_revoke_then_repair(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    code = client.post("/remote/pairing/start").json()["pairing_code"]
    first = client.post(
        "/remote/pairing/complete",
        json={"pairing_code": code, "device_name": "first"},
    ).json()
    client.delete(f"/remote/devices/{first['device_id']}")
    code2 = client.post("/remote/pairing/start").json()["pairing_code"]
    second = client.post(
        "/remote/pairing/complete",
        json={"pairing_code": code2, "device_name": "second"},
    )
    assert second.status_code == 200


def test_pairing_via_gateway_header(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/remote/pairing/start",
        headers={"X-Agentic-OS-Gateway": "1"},
    )
    assert response.status_code == 200
