from __future__ import annotations

from pathlib import Path

from agentic_os.approvals import ApprovalCreate, ApprovalStore
from agentic_os.audit import AuditStore
from test_api import make_client

GATEWAY_HEADERS = {"X-Agentic-OS-Gateway": "1"}


def _db_path(tmp_path: Path) -> Path:
    db = tmp_path / ".agentic-os" / "agentic-os.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    return db


def _audit(tmp_path: Path) -> AuditStore:
    store = AuditStore(_db_path(tmp_path))
    store.init()
    return store


def _approvals(tmp_path: Path) -> ApprovalStore:
    store = ApprovalStore(_db_path(tmp_path))
    store.init()
    return store


def _pair_device(client, *, device_name: str = "approval-phone") -> str:
    code = client.post("/remote/pairing/start").json()["pairing_code"]
    return client.post(
        "/remote/pairing/complete",
        json={"pairing_code": code, "device_name": device_name},
    ).json()["auth_token"]


def test_remote_stream_includes_config_and_approval_events(tmp_path: Path) -> None:
    audit = _audit(tmp_path)
    audit.record("config_patch", "agentic-os", "config_patched", "patch applied", {})
    audit.record(
        "governance", "shell", "approval_requested", "approval ap_1 requested",
        {"approval_id": "ap_1"},
    )
    audit.record(
        "governance", "shell", "approval_rejected", "approval ap_1 rejected",
        {"approval_id": "ap_1"},
    )

    rows = audit.list_remote_stream_events_after_id(0)
    event_types = {row.event_type for row in rows}
    assert "config_patched" in event_types
    assert "approval_requested" in event_types
    assert "approval_rejected" in event_types
    # ordering is by ascending id so a remote cursor never rewinds
    assert [row.id for row in rows] == sorted(row.id for row in rows)


def test_remote_stream_excludes_non_approval_governance(tmp_path: Path) -> None:
    audit = _audit(tmp_path)
    audit.record(
        "governance", "shell", "policy_evaluated", "approval_required: needs review",
        {"session_id": "s1"},
    )
    audit.record(
        "governance", "shell", "approval_requested", "approval ap_2 requested",
        {"approval_id": "ap_2"},
    )

    rows = audit.list_remote_stream_events_after_id(0)
    event_types = {row.event_type for row in rows}
    assert "approval_requested" in event_types
    assert "policy_evaluated" not in event_types


def test_remote_stream_respects_cursor(tmp_path: Path) -> None:
    audit = _audit(tmp_path)
    first = audit.record(
        "governance", "shell", "approval_requested", "first", {"approval_id": "ap_a"}
    )
    audit.record(
        "governance", "shell", "approval_approved", "second", {"approval_id": "ap_a"}
    )
    rows = audit.list_remote_stream_events_after_id(first.id)
    assert {row.event_type for row in rows} == {"approval_approved"}


def test_gateway_client_can_list_approvals(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    token = _pair_device(client)
    headers = {**GATEWAY_HEADERS, "Authorization": f"Bearer {token}"}
    response = client.get("/approvals", headers=headers)
    assert response.status_code == 200
    assert "approvals" in response.json()


def test_gateway_approvals_require_bearer(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.get("/approvals", headers=GATEWAY_HEADERS).status_code == 401


def test_gateway_client_can_resolve_approval(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    token = _pair_device(client)
    pending = _approvals(tmp_path).create(
        ApprovalCreate(
            source_session_id="s1",
            agent_id="shell",
            cwd="/tmp",
            argv=["echo", "hi"],
            env={},
            reason="needs remote review",
        )
    )
    headers = {**GATEWAY_HEADERS, "Authorization": f"Bearer {token}"}
    response = client.post(
        f"/approvals/{pending.id}/reject",
        headers=headers,
        json={"reason": "declined from phone"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
