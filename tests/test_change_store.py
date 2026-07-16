from agentic_os.change_models import ChangePlan
from agentic_os.change_store import ChangeStore


def sample_plan(environment_id: str) -> ChangePlan:
    return ChangePlan.previewed(
        operation="mcp.copy",
        environment_id=environment_id,
        target_surfaces=["config"],
        redacted_request={"server": "context7"},
        before_evidence={"mtime_ns": 10},
        diff={"added": ["mcp_servers.context7"]},
        validation={"ok": True},
    )


def test_change_plan_round_trip(tmp_path) -> None:
    store = ChangeStore(tmp_path / "state.db")
    store.init()
    plan = ChangePlan.previewed(
        operation="mcp.copy",
        environment_id="codex",
        target_surfaces=["config"],
        redacted_request={
            "server": "context7",
            "from_tool": "claude",
            "to_tool": "codex",
        },
        before_evidence={"mtime_ns": 10},
        diff={"added": ["mcp_servers.context7"]},
        validation={"ok": True},
    )

    store.create(plan)

    assert store.get(plan.id) == plan


def test_change_store_lists_newest_first(tmp_path) -> None:
    store = ChangeStore(tmp_path / "state.db")
    store.init()
    first = sample_plan("one")
    second = sample_plan("two")

    store.create(first)
    store.create(second)

    assert [item.id for item in store.list()] == [second.id, first.id]


def test_change_store_updates_full_validated_payload(tmp_path) -> None:
    store = ChangeStore(tmp_path / "state.db")
    store.init()
    plan = sample_plan("codex")
    store.create(plan)

    updated = plan.model_copy(
        update={
            "status": "verified",
            "backup_ref": "patch_123",
            "apply_result": {"changed": True},
        }
    )
    store.update(updated)

    assert store.get(plan.id) == updated


def test_change_store_counts_only_attention_statuses_by_environment(tmp_path) -> None:
    store = ChangeStore(tmp_path / "state.db")
    store.init()
    statuses = [
        "previewed",
        "approved",
        "applying",
        "partial",
        "failed",
        "rollback_failed",
        "verified",
        "stale",
        "rolled_back",
    ]
    for status in statuses:
        plan = sample_plan("codex").with_updates(status=status)
        store.create(plan)
    store.create(sample_plan("claude"))

    assert store.count_pending("codex") == 6
    assert store.count_pending("claude") == 1
    assert store.count_pending("cursor") == 0
