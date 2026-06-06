from __future__ import annotations

from pathlib import Path

import pytest

from agentic_os.remote_access import RemoteAccessError, RemoteAccessService
from test_api import make_client

GATEWAY_HEADERS = {"X-Agentic-OS-Gateway": "1"}


def test_pairing_start_and_complete(tmp_path: Path) -> None:
    svc = RemoteAccessService(tmp_path / ".agentic-os")
    started = svc.start_pairing(ttl_seconds=300)
    assert len(started["pairing_code"]) >= 16
    completed = svc.complete_pairing(
        pairing_code=started["pairing_code"],
        device_name="iphone-test",
        client_key="testclient",
    )
    assert completed["device_id"]
    assert completed["auth_token"]
    assert svc.validate_token(completed["auth_token"]) == completed["device_id"]


def test_pairing_rejects_invalid_code(tmp_path: Path) -> None:
    svc = RemoteAccessService(tmp_path / ".agentic-os")
    with pytest.raises(RemoteAccessError):
        svc.complete_pairing(
            pairing_code="not-a-valid-code",
            device_name="bad",
            client_key="testclient",
        )


def test_pairing_rate_limit(tmp_path: Path) -> None:
    svc = RemoteAccessService(tmp_path / ".agentic-os")
    client_key = "rate-test"
    for _ in range(10):
        with pytest.raises(RemoteAccessError):
            svc.complete_pairing(
                pairing_code="missing",
                device_name="bad",
                client_key=client_key,
            )
    with pytest.raises(RemoteAccessError, match="pairing_rate_limited"):
        svc.ensure_complete_allowed(client_key)


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


def test_remote_admin_routes_reject_gateway_header(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.post("/remote/pairing/start", headers=GATEWAY_HEADERS).status_code == 403
    assert client.get("/remote/devices", headers=GATEWAY_HEADERS).status_code == 403
    assert (
        client.delete("/remote/devices/example", headers=GATEWAY_HEADERS).status_code == 403
    )


def test_gateway_proxied_sessions_require_bearer(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.get("/sessions", headers=GATEWAY_HEADERS).status_code == 401
    assert client.post("/sessions", headers=GATEWAY_HEADERS, json={}).status_code == 401


def test_gateway_pairing_complete_allowed(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    code = client.post("/remote/pairing/start").json()["pairing_code"]
    response = client.post(
        "/remote/pairing/complete",
        headers=GATEWAY_HEADERS,
        json={"pairing_code": code, "device_name": "gateway-client"},
    )
    assert response.status_code == 200
    assert response.json()["auth_token"]


def test_gateway_proxied_sessions_allow_valid_bearer(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    code = client.post("/remote/pairing/start").json()["pairing_code"]
    token = client.post(
        "/remote/pairing/complete",
        json={"pairing_code": code, "device_name": "api-client"},
    ).json()["auth_token"]
    headers = {**GATEWAY_HEADERS, "Authorization": f"Bearer {token}"}
    assert client.get("/sessions", headers=headers).status_code == 200
