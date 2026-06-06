from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agentic_os.remote_access import RemoteAccessService
from agentic_os.remote_store import RemoteDeviceStore
from test_api import make_client

GATEWAY_HEADERS = {"X-Agentic-OS-Gateway": "1"}


def _service(tmp_path: Path) -> RemoteAccessService:
    return RemoteAccessService(tmp_path / ".agentic-os")


def _pair(svc: RemoteAccessService, *, ttl_seconds: int | None = None) -> dict[str, str]:
    started = svc.start_pairing(ttl_seconds=300)
    return svc.complete_pairing(
        pairing_code=started["pairing_code"],
        device_name="phone",
        client_key="testclient",
        ttl_seconds=ttl_seconds,
    )


def test_token_without_ttl_never_expires(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    paired = _pair(svc)  # P12 default: no expiry
    assert svc.validate_token(paired["auth_token"]) == paired["device_id"]


def test_token_with_future_ttl_validates(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    paired = _pair(svc, ttl_seconds=3600)
    assert svc.validate_token(paired["auth_token"]) == paired["device_id"]


def test_expired_token_is_rejected(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    paired = _pair(svc)
    # Force the device's expiry into the past directly in the store.
    store = RemoteDeviceStore(tmp_path / ".agentic-os")
    past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    store.set_device_expiry(paired["device_id"], past)
    assert svc.validate_token(paired["auth_token"]) is None


def test_legacy_device_row_without_expiry_validates(tmp_path: Path) -> None:
    # Simulate a P12 database: devices table created without the expires_at column.
    state = tmp_path / ".agentic-os"
    state.mkdir(parents=True, exist_ok=True)
    import sqlite3

    db = state / "remote_devices.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE devices (
            device_id TEXT PRIMARY KEY,
            device_name TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """
    )
    import hashlib

    token = "legacy-token"
    conn.execute(
        "INSERT INTO devices (device_id, device_name, token_hash, created_at, revoked_at)"
        " VALUES (?, ?, ?, ?, NULL)",
        ("dev-legacy", "old", hashlib.sha256(token.encode()).hexdigest(), "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    # Opening the service migrates the table in place; the legacy token still works.
    svc = _service(tmp_path)
    assert svc.validate_token(token) == "dev-legacy"


def test_rotate_invalidates_old_token_and_preserves_identity(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    paired = _pair(svc)
    old_token = paired["auth_token"]
    device_id = paired["device_id"]

    rotated = svc.rotate_device(device_id)
    assert rotated is not None
    assert rotated["device_id"] == device_id
    assert rotated["auth_token"] != old_token
    assert svc.validate_token(old_token) is None
    assert svc.validate_token(rotated["auth_token"]) == device_id


def test_rotate_missing_or_revoked_device_returns_none(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    assert svc.rotate_device("does-not-exist") is None
    paired = _pair(svc)
    svc.revoke_device(paired["device_id"])
    assert svc.rotate_device(paired["device_id"]) is None


def test_list_devices_includes_expires_at(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    _pair(svc, ttl_seconds=3600)
    devices = svc.list_devices()
    assert len(devices) == 1
    assert "expires_at" in devices[0]
    assert devices[0]["expires_at"] is not None


def test_rotate_route_is_localhost_only(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    code = client.post("/remote/pairing/start").json()["pairing_code"]
    paired = client.post(
        "/remote/pairing/complete",
        json={"pairing_code": code, "device_name": "phone"},
    ).json()
    device_id = paired["device_id"]

    # Through the gateway → forbidden (admin route).
    blocked = client.post(f"/remote/devices/{device_id}/rotate", headers=GATEWAY_HEADERS)
    assert blocked.status_code == 403

    # Localhost operator → rotates, old token now rejected.
    rotated = client.post(f"/remote/devices/{device_id}/rotate")
    assert rotated.status_code == 200
    new_token = rotated.json()["auth_token"]
    assert new_token != paired["auth_token"]

    # Verify via a non-streaming gateway route: old token rejected, new token accepted.
    old_headers = {**GATEWAY_HEADERS, "Authorization": f"Bearer {paired['auth_token']}"}
    new_headers = {**GATEWAY_HEADERS, "Authorization": f"Bearer {new_token}"}
    assert client.get("/sessions", headers=old_headers).status_code == 401
    assert client.get("/sessions", headers=new_headers).status_code == 200


def test_rotate_unknown_device_returns_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.post("/remote/devices/nope/rotate").status_code == 404
