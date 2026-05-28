from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class HealthState(StrEnum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


HEALTH_STATE_SQL = ", ".join(f"'{s.value}'" for s in HealthState)

FLEET_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS fleet_health (
  agent_id TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK (state IN ({HEALTH_STATE_SQL})),
  message TEXT NOT NULL DEFAULT '',
  version TEXT,
  config_fingerprint TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fleet_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{{}}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class HealthRecord:
    agent_id: str
    state: HealthState
    message: str
    version: str | None
    config_fingerprint: str | None
    updated_at: str


@dataclass(frozen=True)
class FleetEvent:
    id: int
    agent_id: str
    event_type: str
    message: str
    metadata: dict[str, object]
    created_at: str


class FleetStore:
    MAX_RUNNING_SESSIONS = 50
    MAX_REGISTERED_INSTANCES = 100

    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(FLEET_SCHEMA)

    def record_health(
        self,
        agent_id: str,
        state: HealthState,
        message: str,
        *,
        version: str | None = None,
        config_fingerprint: str | None = None,
    ) -> HealthRecord:
        previous = self.get_health(agent_id)
        previous_state = previous.state if previous else HealthState.UNKNOWN

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fleet_health (agent_id, state, message, version, config_fingerprint, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(agent_id) DO UPDATE SET
                  state = excluded.state,
                  message = excluded.message,
                  version = excluded.version,
                  config_fingerprint = excluded.config_fingerprint,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (agent_id, state.value, message, version, config_fingerprint),
            )

        if previous_state != state:
            self._record_event(
                agent_id,
                "health_state_changed",
                f"{previous_state.value} -> {state.value}: {message}",
                {"from_state": previous_state.value, "to_state": state.value},
            )

        # Drift detection (G3): only when previous record exists
        if previous is not None:
            if version is not None and previous.version is not None and version != previous.version:
                self._record_event(
                    agent_id,
                    "config_drift_detected",
                    f"version changed: {previous.version} -> {version}",
                    {"field": "version", "previous": previous.version, "current": version},
                )
            if (
                config_fingerprint is not None
                and previous.config_fingerprint is not None
                and config_fingerprint != previous.config_fingerprint
            ):
                self._record_event(
                    agent_id,
                    "config_drift_detected",
                    f"config_fingerprint changed: {previous.config_fingerprint} -> {config_fingerprint}",
                    {
                        "field": "config_fingerprint",
                        "previous": previous.config_fingerprint,
                        "current": config_fingerprint,
                    },
                )

        return self.get_health(agent_id)  # type: ignore[return-value]

    def get_health(self, agent_id: str) -> HealthRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM fleet_health WHERE agent_id = ?", (agent_id,)
            ).fetchone()
        if row is None:
            return None
        return _health_from_row(row)

    def list_health(self) -> list[HealthRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM fleet_health ORDER BY agent_id").fetchall()
        return [_health_from_row(row) for row in rows]

    def list_events(
        self,
        agent_id: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
    ) -> list[FleetEvent]:
        clauses: list[str] = []
        params: list[object] = []
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM fleet_events {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def get_capacity(
        self,
        running_sessions: int,
        registered_instances: int,
    ) -> dict[str, object]:
        return {
            "running_sessions": running_sessions,
            "max_running_sessions": self.MAX_RUNNING_SESSIONS,
            "registered_instances": registered_instances,
            "max_registered_instances": self.MAX_REGISTERED_INSTANCES,
            "at_session_limit": running_sessions >= self.MAX_RUNNING_SESSIONS,
            "at_instance_limit": registered_instances >= self.MAX_REGISTERED_INSTANCES,
        }

    def _record_event(
        self,
        agent_id: str,
        event_type: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fleet_events (agent_id, event_type, message, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (agent_id, event_type, message, json.dumps(metadata or {})),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _health_from_row(row: sqlite3.Row) -> HealthRecord:
    return HealthRecord(
        agent_id=row["agent_id"],
        state=HealthState(row["state"]),
        message=row["message"],
        version=row["version"],
        config_fingerprint=row["config_fingerprint"],
        updated_at=row["updated_at"],
    )


def _event_from_row(row: sqlite3.Row) -> FleetEvent:
    return FleetEvent(
        id=row["id"],
        agent_id=row["agent_id"],
        event_type=row["event_type"],
        message=row["message"],
        metadata=json.loads(row["metadata_json"]),
        created_at=row["created_at"],
    )
