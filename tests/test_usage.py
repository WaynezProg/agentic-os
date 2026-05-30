from pathlib import Path

from agentic_os.usage import (
    FallbackUsageParser,
    OpenclawUsageParser,
    UsageRecord,
    UsageStore,
    _ParsedLogLine,
    read_usage_parser,
)


def test_openclaw_parser_extracts_token_numbers() -> None:
    lines = [
        _ParsedLogLine(
            line='{"usage":{"input_tokens":10,"output_tokens":20},"cost":{"usd":0.0014}}',
            stream="stdout",
        )
    ]
    usage = OpenclawUsageParser().extract(
        session_id="s1",
        harness_id="openclaw",
        lines=lines,
    )
    assert usage.input_tokens == 10
    assert usage.output_tokens == 20
    assert usage.total_tokens == 30
    assert usage.cost_usd == 0.0014


def test_openclaw_parser_extracts_metadata_fields_independently() -> None:
    lines = [
        _ParsedLogLine(
            line=(
                '{"provider":"anthropic","model":"claude-3-5-sonnet",'
                '"run_profile":"work","cwd":"/repo","started_at":"start","ended_at":"end",'
                '"usage":{"input_tokens":10,"output_tokens":20}}'
            ),
            stream="stdout",
        )
    ]

    usage = OpenclawUsageParser().extract(
        session_id="s1",
        harness_id="openclaw",
        lines=lines,
    )

    assert usage.provider == "anthropic"
    assert usage.model == "claude-3-5-sonnet"
    assert usage.run_profile == "work"
    assert usage.cwd == "/repo"
    assert usage.started_at == "start"
    assert usage.ended_at == "end"


def test_fallback_parser_matches_token_count_with_spacing() -> None:
    usage = FallbackUsageParser().extract(
        session_id="sid",
        harness_id="unknown",
        lines=[_ParsedLogLine(line="total tokens: 123", stream="stderr")],
    )

    assert usage.total_tokens == 123


def test_usage_store_round_trip(tmp_path: Path) -> None:
    store = UsageStore(tmp_path / "usage.db")
    store.init()
    record = UsageRecord(
        session_id="s1",
        harness_id="shell",
        provider="local",
        model="local-model",
        run_profile="default",
        cwd="/tmp",
        started_at="2026-05-30T00:00:00Z",
        ended_at="2026-05-30T00:01:00Z",
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
        cost_usd=0.01,
    )
    store.upsert(record)
    loaded = store.get("s1")
    assert loaded.total_tokens == 3
    assert loaded.cost_usd == 0.01


def test_fallback_parser_and_unknown_harness() -> None:
    usage = FallbackUsageParser().extract(
        session_id="sid",
        harness_id="unknown",
        lines=[],
    )
    assert usage.total_tokens == 0
    assert usage.source == "fallback"
    assert read_usage_parser("unknown").source == "fallback"


def test_raw_evidence_is_stable_digest() -> None:
    lines = [
        _ParsedLogLine(line="a", stream="stdout"),
        _ParsedLogLine(line="b", stream="stdout"),
    ]
    record = FallbackUsageParser().extract(
        session_id="sid",
        harness_id="claude",
        lines=lines,
    )
    assert len(record.raw_evidence) == 16
