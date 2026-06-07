from __future__ import annotations

from pathlib import Path

import pytest

from agentic_os.remote_access import RemoteAccessError, RemoteAccessService
from agentic_os.remote_affordances import (
    LOCALHOST_ONLY_ACTIONS,
    LOCALHOST_ONLY_ACTION_SPECS,
    UI_LOCALHOST_ONLY_ACTIONS,
    affordance_localhost_only_actions,
    localhost_only_route_action_id,
)
from agentic_os.remote_gateway import is_remote_admin_route
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


def _require_localhost_operator_route_examples() -> list[tuple[str, str]]:
    return [
        ("POST", "/remote/pairing/start"),
        ("GET", "/remote/devices"),
        ("DELETE", "/remote/devices/example-device"),
        ("POST", "/remote/devices/example-device/rotate"),
        ("POST", "/workspaces"),
        ("PUT", "/workspaces/active"),
        ("POST", "/run-templates"),
        ("PUT", "/run-templates/example-template"),
        ("DELETE", "/run-templates/example-template"),
    ]


def _example_path(template: str) -> str:
    parts: list[str] = []
    for seg in template.split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            parts.append("sample/nested" if seg[1:-1].endswith(":path") else "sample")
        else:
            parts.append(seg)
    return "/".join(parts)


def test_localhost_only_affordances_match_guards(tmp_path: Path) -> None:
    spec_ids = {spec.id for spec in LOCALHOST_ONLY_ACTION_SPECS}
    assert spec_ids == LOCALHOST_ONLY_ACTIONS

    for method, path in _require_localhost_operator_route_examples():
        action_id = localhost_only_route_action_id(method, path)
        assert action_id is not None
        assert action_id in LOCALHOST_ONLY_ACTIONS
        assert is_remote_admin_route(method, path)

    for method, path in _require_localhost_operator_route_examples():
        action_id = localhost_only_route_action_id(method, path)
        assert action_id is not None
        assert action_id in LOCALHOST_ONLY_ACTIONS
        assert is_remote_admin_route(method, path)

    assert localhost_only_route_action_id("POST", "/remote/pairing/complete") is None
    assert not is_remote_admin_route("POST", "/remote/pairing/complete")

    # Enforcement is structural: the remote gateway middleware rejects every
    # registered localhost-only action for a gateway (non-localhost) client.
    # Asserting the behaviour for every spec is stronger than counting guard
    # call sites and cannot silently regress when a new action is added.
    enforcement_client = make_client(tmp_path)
    for spec in LOCALHOST_ONLY_ACTION_SPECS:
        path = _example_path(spec.path_template)
        rejected = enforcement_client.request(spec.method, path, headers=GATEWAY_HEADERS, json={})
        assert rejected.status_code == 403, f"{spec.id} ({spec.method} {path}) not enforced for gateway client"

    client = make_client(tmp_path)
    response = client.get("/remote/affordances")
    assert response.status_code == 200
    assert set(response.json()["localhost_only"]) == affordance_localhost_only_actions()
    assert UI_LOCALHOST_ONLY_ACTIONS.issubset(affordance_localhost_only_actions())


def test_gateway_proxied_sessions_allow_valid_bearer(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    code = client.post("/remote/pairing/start").json()["pairing_code"]
    token = client.post(
        "/remote/pairing/complete",
        json={"pairing_code": code, "device_name": "api-client"},
    ).json()["auth_token"]
    headers = {**GATEWAY_HEADERS, "Authorization": f"Bearer {token}"}
    assert client.get("/sessions", headers=headers).status_code == 200
