from __future__ import annotations

from pathlib import Path

from agentic_os.audit import AuditStore


def _make_store(tmp_path: Path) -> AuditStore:
    store = AuditStore(tmp_path / "audit.db")
    store.init()
    return store


def test_audit_store_records_and_lists_events(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    event = store.record("skill", "reviewer", "skill_upserted", "created skill reviewer")
    assert event.id >= 1
    assert event.domain == "skill"
    assert event.entity_id == "reviewer"
    assert event.event_type == "skill_upserted"
    assert event.message == "created skill reviewer"
    assert event.metadata == {}

    events = store.list_events()
    assert len(events) == 1
    assert events[0].id == event.id


def test_audit_store_records_with_metadata(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    meta = {"field": "enabled", "before": True, "after": False}
    event = store.record("mcp", "filesystem", "mcp_disabled", "disabled", metadata=meta)
    assert event.metadata == meta


def test_audit_store_filters_by_domain_entity_and_type(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.record("skill", "reviewer", "skill_upserted", "upsert")
    store.record("mcp", "filesystem", "mcp_upserted", "upsert")
    store.record("skill", "reviewer", "skill_disabled", "disabled")

    assert len(store.list_events(domain="skill")) == 2
    assert len(store.list_events(domain="mcp")) == 1
    assert len(store.list_events(entity_id="reviewer")) == 2
    assert len(store.list_events(event_type="skill_upserted")) == 1
    assert len(store.list_events(domain="skill", event_type="skill_disabled")) == 1


def test_audit_store_limit_orders_desc(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.record("skill", "a", "skill_upserted", "first")
    store.record("skill", "b", "skill_upserted", "second")
    store.record("skill", "c", "skill_upserted", "third")

    events = store.list_events(limit=2)
    assert len(events) == 2
    assert events[0].entity_id == "c"  # newest first
    assert events[1].entity_id == "b"


def test_policy_coverage_reports_missing_policy_and_uncovered_runs(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    # agent "shell" has no policy_upserted event and no policy_evaluated events
    result = store.policy_coverage(
        agent_ids=["shell"],
        session_ids_by_agent={"shell": ["s_1", "s_2"]},
        policy_agent_ids=[],
    )
    assert len(result) == 1
    assert result[0]["agent_id"] == "shell"
    assert result[0]["has_policy"] is False
    assert result[0]["last_evaluated_at"] is None
    assert result[0]["recent_run_count"] == 2
    assert result[0]["runs_without_policy_evaluation"] == ["s_1", "s_2"]


def test_policy_coverage_reports_last_evaluated_at(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    # Record policy upsert and evaluation
    store.record("policy", "shell", "policy_upserted", "created")
    store.record(
        "governance",
        "shell",
        "policy_evaluated",
        "allow",
        metadata={"session_id": "s_1", "decision": "allow"},
    )

    result = store.policy_coverage(
        agent_ids=["shell"],
        session_ids_by_agent={"shell": ["s_1", "s_2"]},
        policy_agent_ids=["shell"],
    )
    assert result[0]["has_policy"] is True
    assert result[0]["last_evaluated_at"] is not None
    assert result[0]["runs_without_policy_evaluation"] == ["s_2"]


def test_policy_coverage_uses_current_policy_rows_not_audit_history(tmp_path: Path) -> None:
    store = _make_store(tmp_path)

    result = store.policy_coverage(
        agent_ids=["shell"],
        session_ids_by_agent={},
        policy_agent_ids=["shell"],
    )

    assert result[0]["has_policy"] is True
