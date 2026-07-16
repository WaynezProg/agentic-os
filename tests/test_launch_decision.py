from __future__ import annotations

from pathlib import Path

from agentic_os.control_plane import ControlPlaneStore, PolicyUpsert
from agentic_os.launch_decision import LaunchContext, LaunchDecisionService


def _service(tmp_path: Path) -> tuple[LaunchDecisionService, ControlPlaneStore]:
    store = ControlPlaneStore(tmp_path / "state.db")
    store.init()
    return LaunchDecisionService(store), store


def _context(**updates: object) -> LaunchContext:
    values: dict[str, object] = {
        "agent_id": "shell",
        "cwd": "/tmp/project",
        "running_sessions": 0,
        "max_running_sessions": 50,
    }
    values.update(updates)
    return LaunchContext.model_validate(values)


def test_missing_policy_is_open_with_warning(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    decision = service.evaluate(_context())

    assert decision.decision == "allow"
    assert decision.reason == "policy_missing_open_default"
    assert decision.warnings == ["no launch policy configured"]
    assert decision.policy_present is False


def test_capacity_denial_precedes_policy(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    store.upsert_policy(
        "shell",
        PolicyUpsert(enabled=True, cwd_roots=["/tmp"]),
    )

    decision = service.evaluate(
        _context(running_sessions=50, max_running_sessions=50)
    )

    assert decision.decision == "deny"
    assert decision.reason == "capacity_limit_reached"


def test_session_start_approval_requirement_is_preserved(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    store.upsert_policy(
        "shell",
        PolicyUpsert(
            enabled=True,
            allowed_tool_names=["*"],
            approval_required_tool_names=["session.start"],
            cwd_roots=["/tmp"],
        ),
    )

    decision = service.evaluate(_context())

    assert decision.decision == "approval_required"
    assert "session.start" in decision.detail


def test_granted_approval_converts_requirement_to_allow(tmp_path: Path) -> None:
    service, store = _service(tmp_path)
    store.upsert_policy(
        "shell",
        PolicyUpsert(
            enabled=True,
            allowed_tool_names=["*"],
            approval_required_tool_names=["session.start"],
            cwd_roots=["/tmp"],
        ),
    )

    decision = service.evaluate(_context(approval_granted=True, require_policy=True))

    assert decision.decision == "allow"
    assert decision.reason == "approval_granted"


def test_approval_revalidation_requires_policy_to_still_exist(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    decision = service.evaluate(_context(require_policy=True))

    assert decision.decision == "deny"
    assert decision.reason == "policy_missing"
