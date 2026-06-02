from __future__ import annotations

import json
from pathlib import Path

from agentic_os.evidence import EvidenceStore
from agentic_os.models import SessionCreate
from agentic_os.storage import Store


def make_session(tmp_path: Path, *, agent_id: str = "codex", argv: list[str] | None = None):
    store = Store(tmp_path / "agentic-os.db")
    store.init()
    session_dir = tmp_path / "sessions" / "s_manual"
    return store.create_session(
        SessionCreate(
            agent_id=agent_id,
            cwd=str(tmp_path),
            argv=argv or ["/bin/sh", "-lc", "printf OK"],
            env={"SECRET_TOKEN": "hidden", "VISIBLE_NAME": "shown"},
            artifact_dir=str(session_dir / "artifacts"),
            stdout_log=str(session_dir / "stdout.jsonl"),
            stderr_log=str(session_dir / "stderr.jsonl"),
            resolved_profile="default",
            resolved_provider="openai",
            resolved_model="gpt-5",
        )
    )


def test_evidence_store_creates_base_bundle(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)

    paths = evidence.ensure_bundle(session)

    assert paths.metadata.exists()
    assert paths.events.exists()
    assert paths.artifact_manifest.exists()
    assert Path(session.artifact_dir).exists()
    manifest = json.loads(paths.artifact_manifest.read_text(encoding="utf-8"))
    assert manifest == {
        "schema_version": "artifact_manifest.v1",
        "session_id": session.id,
        "artifacts": [],
    }


def test_evidence_metadata_redacts_env_values_and_records_paths(tmp_path: Path) -> None:
    session = make_session(tmp_path, agent_id="codex")
    evidence = EvidenceStore(state_dir=tmp_path)

    payload = evidence.write_metadata(session)

    assert payload["schema_version"] == "session_evidence.v1"
    assert payload["session_id"] == session.id
    assert payload["harness_id"] == "codex"
    assert payload["adapter_contract_version"] == "v2"
    assert payload["required_env"] == ["SECRET_TOKEN", "VISIBLE_NAME"]
    assert "hidden" not in json.dumps(payload)
    assert payload["resolved_profile"] == "default"
    assert payload["resolved_provider"] == "openai"
    assert payload["resolved_model"] == "gpt-5"
    assert payload["evidence_paths"]["events"].endswith("/events.jsonl")
    assert payload["evidence_paths"]["artifact_manifest"].endswith("/artifacts/manifest.json")


def test_evidence_metadata_redacts_split_argv_and_key_value_secrets(
    tmp_path: Path,
) -> None:
    session = make_session(
        tmp_path,
        argv=["codex", "exec", "--api-key", "sk-test-secret", "api_key=SECRET_QS"],
    )
    evidence = EvidenceStore(state_dir=tmp_path)

    payload = evidence.write_metadata(session)

    metadata_text = (Path(session.stdout_log).parent / "metadata.json").read_text(encoding="utf-8")
    assert payload["argv"] == [
        "codex",
        "exec",
        "--api-key",
        "[REDACTED]",
        "api_key=[REDACTED]",
    ]
    assert "sk-test-secret" not in metadata_text
    assert "SECRET_QS" not in metadata_text
    assert "sk-test-secret" not in json.dumps(payload)
    assert "SECRET_QS" not in json.dumps(payload)


def test_evidence_metadata_uses_v1_for_non_semantic_harness(tmp_path: Path) -> None:
    session = make_session(tmp_path, agent_id="shell")
    evidence = EvidenceStore(state_dir=tmp_path)

    payload = evidence.write_metadata(session)

    assert payload["adapter_contract_version"] == "v1"


def test_evidence_events_append_and_read_with_truncation(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)

    evidence.append_event(session, "run_accepted", "run accepted", {"argv": session.argv})
    evidence.append_event(session, "process_started", "process started", {"pid": 123})
    result = evidence.read_events(session, max_lines=1)

    assert result.truncated is True
    assert len(result.events) == 1
    assert result.events[0].event_type == "run_accepted"
    assert result.events[0].severity == "info"
    assert result.events[0].metadata == {"argv": session.argv}
    assert result.events[0].index == 1


def test_evidence_event_message_is_redacted(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)

    evidence.append_event(session, "auth_failed", "token=SECRET_MESSAGE")

    event_text = (Path(session.stdout_log).parent / "events.jsonl").read_text(encoding="utf-8")
    result = evidence.read_events(session)
    assert "SECRET_MESSAGE" not in event_text
    assert result.events[0].message == "token=[REDACTED]"


def test_evidence_event_metadata_redacts_split_argv_secrets(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)

    evidence.append_event(
        session,
        "run_accepted",
        "run accepted",
        {"argv": ["--api-key", "sk-test-secret"]},
    )

    event_text = (Path(session.stdout_log).parent / "events.jsonl").read_text(encoding="utf-8")
    result = evidence.read_events(session)
    assert "sk-test-secret" not in event_text
    assert result.events[0].metadata == {"argv": ["--api-key", "[REDACTED]"]}


def test_evidence_event_metadata_preserves_usage_token_counts(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)

    evidence.append_event(
        session,
        "usage_reported",
        "usage reported",
        {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
    )

    result = evidence.read_events(session)

    assert result.events[0].metadata == {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
    }


def test_evidence_event_reader_skips_malformed_jsonl(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)
    paths = evidence.ensure_bundle(session)
    paths.events.write_text(
        "not-json\n"
        + json.dumps(
            {
                "ts": "2026-06-02T00:00:00+00:00",
                "session_id": session.id,
                "harness_id": session.agent_id,
                "event_type": "process_exited",
                "severity": "info",
                "message": "process exited",
                "metadata": {"exit_code": 0},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = evidence.read_events(session)

    assert result.truncated is False
    assert [event.event_type for event in result.events] == ["process_exited"]
    assert result.events[0].index == 2


def test_evidence_records_artifact_manifest_entry(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    evidence = EvidenceStore(state_dir=tmp_path)
    artifact_path = Path(session.artifact_dir) / "report.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text('{"ok": true}', encoding="utf-8")

    entry = evidence.record_artifact(
        session,
        artifact_path,
        kind="json",
        media_type="application/json",
        source_event_type="artifact_recorded",
    )

    manifest = json.loads(
        (Path(session.artifact_dir) / "manifest.json").read_text(encoding="utf-8")
    )
    assert entry["id"] == "art_001"
    assert entry["path"].endswith("/artifacts/report.json")
    assert entry["sha256"]
    assert manifest["artifacts"] == [entry]
