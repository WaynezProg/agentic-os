from __future__ import annotations

from pathlib import Path

import pytest

from agentic_os.approvals import ApprovalCreate, ApprovalStatus, ApprovalStore


def make_store(tmp_path: Path) -> ApprovalStore:
    store = ApprovalStore(tmp_path / "agentic-os.db")
    store.init()
    return store


def test_create_list_show_and_reject_approval(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    approval = store.create(
        ApprovalCreate(
            source_session_id="s_blocked",
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/usr/bin/printf", "OK"],
            env={"A": "B"},
            reason="session.start requires approval",
        )
    )

    assert approval.status == ApprovalStatus.PENDING
    assert approval.source_session_id == "s_blocked"
    assert approval.argv == ["/usr/bin/printf", "OK"]
    assert approval.env == {"A": "B"}
    assert [item.id for item in store.list()] == [approval.id]

    rejected = store.reject(approval.id, "not needed")

    assert rejected.status == ApprovalStatus.REJECTED
    assert rejected.decision_reason == "not needed"


def test_approve_sets_approved_session_once(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    approval = store.create(
        ApprovalCreate(
            source_session_id="s_blocked",
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/bin/echo", "OK"],
            env={},
            reason="session.start requires approval",
        )
    )

    approved = store.approve(approval.id, approved_session_id="s_started")

    assert approved.status == ApprovalStatus.APPROVED
    assert approved.approved_session_id == "s_started"

    with pytest.raises(ValueError):
        store.reject(approval.id, "too late")


def test_claim_reserves_pending_approval_before_session_is_linked(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    approval = store.create(
        ApprovalCreate(
            source_session_id="s_blocked",
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/bin/echo", "OK"],
            env={},
            reason="session.start requires approval",
        )
    )

    claimed = store.claim(approval.id)

    assert claimed.status == ApprovalStatus.APPROVED
    assert claimed.approved_session_id is None
    with pytest.raises(ValueError):
        store.approve(approval.id, approved_session_id="s_second")

    linked = store.link_approved_session(approval.id, "s_started")

    assert linked.status == ApprovalStatus.APPROVED
    assert linked.approved_session_id == "s_started"


def test_expire_marks_pending_approval_terminal(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    approval = store.create(
        ApprovalCreate(
            source_session_id="s_blocked",
            agent_id="shell",
            cwd=str(tmp_path),
            argv=["/bin/echo", "OK"],
            env={},
            reason="session.start requires approval",
        )
    )

    expired = store.expire(approval.id, "policy no longer allows request")

    assert expired.status == ApprovalStatus.EXPIRED
    assert expired.decision_reason == "policy no longer allows request"
