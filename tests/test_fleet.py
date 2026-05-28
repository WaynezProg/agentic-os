from pathlib import Path

from agentic_os.fleet import FleetStore, HealthState


def _make_store(tmp_path: Path) -> FleetStore:
    store = FleetStore(tmp_path / "fleet.db")
    store.init()
    return store


def test_record_health_and_get(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK")
    record = store.get_health("shell")
    assert record.agent_id == "shell"
    assert record.state == HealthState.UP
    assert record.message == "OK"
    assert record.version is None
    assert record.config_fingerprint is None


def test_record_health_with_version_and_fingerprint(tmp_path):
    store = _make_store(tmp_path)
    store.record_health(
        "shell",
        HealthState.UP,
        "OK",
        version="1.0.0",
        config_fingerprint="abc123",
    )
    record = store.get_health("shell")
    assert record.version == "1.0.0"
    assert record.config_fingerprint == "abc123"


def test_record_health_creates_transition_event(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK")
    store.record_health("shell", HealthState.DOWN, "timeout")
    events = store.list_events()
    transition_events = [e for e in events if e.event_type == "health_state_changed"]
    # First: unknown->up, Second: up->down
    assert len(transition_events) == 2


def test_list_health_all_instances(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK")
    store.record_health("openclaw", HealthState.DOWN, "not found")
    records = store.list_health()
    assert len(records) == 2
    ids = {r.agent_id for r in records}
    assert ids == {"shell", "openclaw"}


def test_get_health_unknown_returns_none(tmp_path):
    store = _make_store(tmp_path)
    assert store.get_health("nonexistent") is None


def test_record_health_drift_event_on_version_change(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="aaa")
    store.record_health("shell", HealthState.UP, "OK", version="1.1.0", config_fingerprint="aaa")
    events = store.list_events(event_type="config_drift_detected")
    assert len(events) == 1
    assert events[0].metadata["field"] == "version"
    assert events[0].metadata["previous"] == "1.0.0"
    assert events[0].metadata["current"] == "1.1.0"


def test_record_health_drift_event_on_fingerprint_change(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="aaa")
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="bbb")
    events = store.list_events(event_type="config_drift_detected")
    assert len(events) == 1
    assert events[0].metadata["field"] == "config_fingerprint"


def test_no_drift_event_when_unchanged(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="aaa")
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="aaa")
    events = store.list_events(event_type="config_drift_detected")
    assert len(events) == 0


def test_no_drift_event_on_first_record(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("shell", HealthState.UP, "OK", version="1.0.0", config_fingerprint="aaa")
    events = store.list_events(event_type="config_drift_detected")
    assert len(events) == 0


def test_capacity_query(tmp_path):
    store = _make_store(tmp_path)
    capacity = store.get_capacity(running_sessions=5, registered_instances=10)
    assert capacity["running_sessions"] == 5
    assert capacity["max_running_sessions"] == 50
    assert capacity["registered_instances"] == 10
    assert capacity["max_registered_instances"] == 100
    assert capacity["at_session_limit"] is False
    assert capacity["at_instance_limit"] is False


def test_capacity_at_limit(tmp_path):
    store = _make_store(tmp_path)
    capacity = store.get_capacity(running_sessions=50, registered_instances=100)
    assert capacity["at_session_limit"] is True
    assert capacity["at_instance_limit"] is True


def test_list_events_filter_by_agent(tmp_path):
    store = _make_store(tmp_path)
    store.record_health("a", HealthState.UP, "OK")
    store.record_health("b", HealthState.UP, "OK")
    events_a = store.list_events(agent_id="a")
    assert all(e.agent_id == "a" for e in events_a)


def test_list_events_limit(tmp_path):
    store = _make_store(tmp_path)
    for i in range(5):
        store.record_health(f"agent_{i}", HealthState.UP, "OK")
    events = store.list_events(limit=2)
    assert len(events) == 2
