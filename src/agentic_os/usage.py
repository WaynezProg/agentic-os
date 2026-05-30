from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

USAGE_PARSER_SOURCE_FALLBACK = "fallback"
USAGE_PARSER_SOURCE_OPENCLAW = "openclaw"


@dataclass(frozen=True)
class UsageRecord:
    session_id: str
    harness_id: str
    provider: str
    model: str
    run_profile: str
    cwd: str
    started_at: str
    ended_at: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    currency: str = "USD"
    source: str = USAGE_PARSER_SOURCE_FALLBACK
    raw_evidence: str = "-"

    @property
    def token_total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class _ParsedLogLine:
    line: str
    stream: str
    ts: str | None = None


class UsageParser(Protocol):
    harness_id: str
    source: str

    def extract(self, *, session_id: str, harness_id: str, lines: list[_ParsedLogLine]) -> UsageRecord: ...


class OpenclawUsageParser:
    harness_id = "openclaw"
    source = USAGE_PARSER_SOURCE_OPENCLAW

    def extract(self, *, session_id: str, harness_id: str, lines: list[_ParsedLogLine]) -> UsageRecord:
        input_tokens = 0
        output_tokens = 0
        cost_usd = 0.0

        for entry in lines:
            raw = _parse_json_line(entry.line)
            if raw is None:
                continue

            usage = raw.get("usage", {})
            if isinstance(usage, dict):
                input_tokens += _int_or_zero(usage.get("input_tokens"))
                output_tokens += _int_or_zero(usage.get("output_tokens"))

            if not cost_usd:
                cost_usd = _float_or_zero(raw.get("cost"))
            payload_cost = raw.get("cost")
            if isinstance(payload_cost, dict):
                cost_usd += _float_or_zero(payload_cost.get("usd"))

        total_tokens = input_tokens + output_tokens
        evidence = _evidence_hash(lines)

        return UsageRecord(
            session_id=session_id,
            harness_id=harness_id,
            provider=_extract_field(lines, ["provider", "resolved_provider"]),
            model=_extract_field(lines, ["model", "resolved_model"]),
            run_profile=_extract_field(lines, ["run_profile", "resolved_profile", "profile"]),
            cwd=_extract_field(lines, ["cwd"]),
            started_at=_extract_field(lines, ["started_at"]),
            ended_at=_extract_field(lines, ["ended_at"]),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=round(cost_usd, 4),
            raw_evidence=evidence,
            source=self.source,
        )


class FallbackUsageParser:
    harness_id = "any"
    source = USAGE_PARSER_SOURCE_FALLBACK

    def extract(self, *, session_id: str, harness_id: str, lines: list[_ParsedLogLine]) -> UsageRecord:
        total_tokens = 0
        for entry in lines:
            match = _TOKEN_PATTERN.search(entry.line)
            if match:
                total_tokens += int(match.group("tokens"))

        evidence = _evidence_hash(lines)
        return UsageRecord(
            session_id=session_id,
            harness_id=harness_id,
            provider="",
            model="",
            run_profile="default",
            cwd="unknown",
            started_at="",
            ended_at="",
            input_tokens=0,
            output_tokens=0,
            total_tokens=total_tokens,
            cost_usd=0.0,
            raw_evidence=evidence,
            source=self.source,
        )


_PARSERS: list[UsageParser] = [OpenclawUsageParser(), FallbackUsageParser()]
_TOKEN_PATTERN = re.compile(r"\btokens?\b\s*[:=]?\s*(?P<tokens>\d+)", re.IGNORECASE)


def read_usage_parser(harness_id: str) -> UsageParser:
    for parser in _PARSERS:
        if parser.harness_id == harness_id:
            return parser
    return FallbackUsageParser()


def parse_logs_for_usage(log_paths: list[Path]) -> list[_ParsedLogLine]:
    entries: list[_ParsedLogLine] = []
    for path in log_paths:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            line_payload = _parse_json_line(raw)
            if isinstance(line_payload, dict) and "line" in line_payload:
                value = line_payload["line"]
            else:
                value = raw
            if not isinstance(value, str):
                continue
            ts = line_payload.get("ts") if isinstance(line_payload, dict) else None
            stream = line_payload.get("stream") if isinstance(line_payload, dict) else None
            stream_name = stream if stream in {"stdout", "stderr"} else "stdout"
            if isinstance(ts, str):
                entries.append(_ParsedLogLine(line=value, stream=stream_name, ts=ts))
            else:
                entries.append(_ParsedLogLine(line=value, stream=stream_name))
    return entries


class UsageStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(USAGE_SCHEMA)
            self._migrate_usage_columns(conn)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, record: UsageRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_records (
                  session_id, harness_id, provider, model, run_profile, cwd, started_at,
                  ended_at, input_tokens, output_tokens, total_tokens, cost_usd, currency,
                  source, raw_evidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  harness_id = excluded.harness_id,
                  provider = excluded.provider,
                  model = excluded.model,
                  run_profile = excluded.run_profile,
                  cwd = excluded.cwd,
                  started_at = excluded.started_at,
                  ended_at = excluded.ended_at,
                  input_tokens = excluded.input_tokens,
                  output_tokens = excluded.output_tokens,
                  total_tokens = excluded.total_tokens,
                  cost_usd = excluded.cost_usd,
                  currency = excluded.currency,
                  source = excluded.source,
                  raw_evidence = excluded.raw_evidence,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    record.session_id,
                    record.harness_id,
                    record.provider,
                    record.model,
                    record.run_profile,
                    record.cwd,
                    record.started_at,
                    record.ended_at,
                    record.input_tokens,
                    record.output_tokens,
                    record.total_tokens,
                    record.cost_usd,
                    record.currency,
                    record.source,
                    record.raw_evidence,
                ),
            )

    def get(self, session_id: str) -> UsageRecord:
        record = self.try_get(session_id)
        if record is None:
            raise KeyError(session_id)
        return record

    def try_get(self, session_id: str) -> UsageRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM usage_records WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return _usage_from_row(row)

    def list_summary(
        self,
        *,
        from_ts: str | None = None,
        to_ts: str | None = None,
        harness_id: str | None = None,
        provider: str | None = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if from_ts is not None:
            clauses.append("started_at >= ?")
            params.append(from_ts)
        if to_ts is not None:
            clauses.append("ended_at <= ?")
            params.append(to_ts)
        if harness_id is not None:
            clauses.append("harness_id = ?")
            params.append(harness_id)
        if provider is not None:
            clauses.append("provider = ?")
            params.append(provider)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM usage_records {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [_usage_row_to_dict(row) for row in rows]

    def list_daily_totals(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  date(updated_at) AS day,
                  COALESCE(SUM(total_tokens), 0) AS total_tokens,
                  COALESCE(SUM(cost_usd), 0.0) AS cost_usd,
                  COUNT(*) AS session_count
                FROM usage_records
                GROUP BY date(updated_at)
                ORDER BY day DESC
                """
            ).fetchall()
        return [
            {
                "day": row["day"],
                "total_tokens": int(row["total_tokens"]),
                "cost_usd": float(row["cost_usd"]),
                "session_count": int(row["session_count"]),
            }
            for row in rows
        ]

    def list_session_totals(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  session_id,
                  harness_id,
                  provider,
                  model,
                  total_tokens,
                  cost_usd
                FROM usage_records
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [_usage_row_to_dict(row) for row in rows]

    def list_for_harnesses(self, limit: int = 100) -> list[UsageRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM usage_records ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_usage_from_row(row) for row in rows]

    def summary(self) -> dict[str, object]:
        with self.connect() as conn:
            totals = conn.execute(
                """
                SELECT
                  COUNT(*) as session_count,
                  COALESCE(SUM(input_tokens), 0) AS input_tokens,
                  COALESCE(SUM(output_tokens), 0) AS output_tokens,
                  COALESCE(SUM(total_tokens), 0) AS total_tokens,
                  COALESCE(SUM(cost_usd), 0.0) AS cost_usd
                FROM usage_records
                """
            ).fetchone()
            by_harness = conn.execute(
                """
                SELECT
                  harness_id,
                  COALESCE(SUM(total_tokens), 0) AS total_tokens,
                  COALESCE(SUM(cost_usd), 0.0) AS cost_usd,
                  COUNT(*) as session_count
                FROM usage_records
                GROUP BY harness_id
                ORDER BY total_tokens DESC
                """
            ).fetchall()

        return {
            "session_count": int(totals["session_count"]),
            "input_tokens": int(totals["input_tokens"]),
            "output_tokens": int(totals["output_tokens"]),
            "total_tokens": int(totals["total_tokens"]),
            "cost_usd": float(totals["cost_usd"]),
            "by_harness": [
                {
                    "harness_id": row["harness_id"],
                    "session_count": int(row["session_count"]),
                    "total_tokens": int(row["total_tokens"]),
                    "cost_usd": float(row["cost_usd"]),
                }
                for row in by_harness
            ],
        }

    def quotas(self) -> dict[str, object]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  provider,
                  model,
                  COALESCE(SUM(total_tokens), 0) AS total_tokens,
                  COALESCE(SUM(cost_usd), 0.0) AS cost_usd,
                  COUNT(*) as session_count
                FROM usage_records
                GROUP BY provider, model
                ORDER BY provider, model
                """
            ).fetchall()

        return {
            "quotas": [
                {
                    "provider": row["provider"],
                    "model": row["model"],
                    "used_tokens": int(row["total_tokens"]),
                    "used_cost_usd": float(row["cost_usd"]),
                    "session_count": int(row["session_count"]),
                    "limit_tokens": None,
                    "limit_cost_usd": None,
                    "currency": "USD",
                    "status": "unlimited",
                }
                for row in rows
            ]
        }

    def _migrate_usage_columns(self, conn: sqlite3.Connection) -> None:
        if not _table_has_column(conn, "usage_records", "currency"):
            conn.execute("ALTER TABLE usage_records ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")
            conn.execute("UPDATE usage_records SET currency = 'USD'")

        if not _table_has_column(conn, "usage_records", "source"):
            conn.execute("ALTER TABLE usage_records ADD COLUMN source TEXT NOT NULL DEFAULT 'fallback'")

        if not _table_has_column(conn, "usage_records", "raw_evidence"):
            conn.execute("ALTER TABLE usage_records ADD COLUMN raw_evidence TEXT NOT NULL DEFAULT '-'")


def _parse_json_line(raw_line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw_line)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _evidence_hash(lines: list[_ParsedLogLine]) -> str:
    payload = "\n".join(line.line for line in lines)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _extract_field(lines: list[_ParsedLogLine], keys: list[str]) -> str:
    for entry in lines:
        payload = _parse_json_line(entry.line)
        if not isinstance(payload, dict):
            continue

        for key in keys:
            if key in payload and isinstance(payload[key], str):
                return payload[key]

        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            for key in keys:
                if key in metadata and isinstance(metadata[key], str):
                    return metadata[key]

    return ""


def _int_or_zero(value: Any) -> int:
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _float_or_zero(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _table_has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return any(row[1] == column_name for row in conn.execute(f"PRAGMA table_info({table_name})"))


def _usage_row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    return {
        "session_id": row["session_id"],
        "harness_id": row["harness_id"],
        "provider": row["provider"],
        "model": row["model"],
        "run_profile": row["run_profile"],
        "cwd": row["cwd"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "input_tokens": int(row["input_tokens"]),
        "output_tokens": int(row["output_tokens"]),
        "total_tokens": int(row["total_tokens"]),
        "cost_usd": float(row["cost_usd"]),
        "currency": row["currency"],
        "source": row["source"],
        "raw_evidence": row["raw_evidence"],
    }


def usage_record_to_dict(record: UsageRecord) -> dict[str, object]:
    return {
        "session_id": record.session_id,
        "harness_id": record.harness_id,
        "provider": record.provider,
        "model": record.model,
        "run_profile": record.run_profile,
        "cwd": record.cwd,
        "started_at": record.started_at,
        "ended_at": record.ended_at,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "total_tokens": record.total_tokens,
        "cost_usd": record.cost_usd,
        "currency": record.currency,
        "source": record.source,
        "raw_evidence": record.raw_evidence,
    }


def _usage_from_row(row: sqlite3.Row) -> UsageRecord:
    return UsageRecord(
        session_id=row["session_id"],
        harness_id=row["harness_id"],
        provider=row["provider"],
        model=row["model"],
        run_profile=row["run_profile"],
        cwd=row["cwd"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        input_tokens=int(row["input_tokens"]),
        output_tokens=int(row["output_tokens"]),
        total_tokens=int(row["total_tokens"]),
        cost_usd=float(row["cost_usd"]),
        currency=row["currency"],
        source=row["source"],
        raw_evidence=row["raw_evidence"],
    )


USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
  session_id TEXT PRIMARY KEY,
  harness_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  run_profile TEXT NOT NULL,
  cwd TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0.0,
  currency TEXT NOT NULL DEFAULT 'USD',
  source TEXT NOT NULL DEFAULT 'fallback',
  raw_evidence TEXT NOT NULL DEFAULT '-',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
