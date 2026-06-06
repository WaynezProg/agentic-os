from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


class RemoteDeviceStore:
    def __init__(self, state_dir: Path) -> None:
        self._db = state_dir / "remote_devices.sqlite3"
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code TEXT PRIMARY KEY,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS pairing_failures (
                    client_key TEXT NOT NULL,
                    failed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pairing_failures_client
                    ON pairing_failures (client_key, failed_at);
                """
            )

    def insert_pairing_code(self, code: str, expires_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pairing_codes (code, expires_at) VALUES (?, ?)",
                (code, expires_at),
            )

    def consume_pairing_code(self, code: str) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT expires_at FROM pairing_codes WHERE code = ?",
                (code,),
            ).fetchone()
            if row is None:
                return False
            if row["expires_at"] < now:
                conn.execute("DELETE FROM pairing_codes WHERE code = ?", (code,))
                return False
            conn.execute("DELETE FROM pairing_codes WHERE code = ?", (code,))
            return True

    def insert_device(self, *, device_id: str, device_name: str, token_hash: str) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO devices (device_id, device_name, token_hash, created_at, revoked_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (device_id, device_name, token_hash, created_at),
            )

    def device_id_for_token_hash(self, token_hash: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT device_id FROM devices
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (token_hash,),
            ).fetchone()
        return row["device_id"] if row else None

    def revoke_device(self, device_id: str) -> bool:
        revoked_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE devices SET revoked_at = ?
                WHERE device_id = ? AND revoked_at IS NULL
                """,
                (revoked_at, device_id),
            )
        return cursor.rowcount > 0

    def list_devices(self) -> list[dict[str, str | None]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT device_id, device_name, created_at, revoked_at
                FROM devices
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [
            {
                "device_id": row["device_id"],
                "device_name": row["device_name"],
                "created_at": row["created_at"],
                "revoked_at": row["revoked_at"],
            }
            for row in rows
        ]

    def count_recent_pairing_failures(self, client_key: str, *, window_seconds: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(seconds=window_seconds)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM pairing_failures
                WHERE client_key = ? AND failed_at >= ?
                """,
                (client_key, cutoff),
            ).fetchone()
        return int(row["count"]) if row else 0

    def record_pairing_failure(self, client_key: str) -> None:
        failed_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pairing_failures (client_key, failed_at) VALUES (?, ?)",
                (client_key, failed_at),
            )

    def clear_pairing_failures(self, client_key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pairing_failures WHERE client_key = ?", (client_key,))
