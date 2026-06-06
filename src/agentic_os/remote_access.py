from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agentic_os.remote_store import RemoteDeviceStore

PAIRING_CODE_BYTES = 16
MAX_PAIRING_FAILURES = 10
PAIRING_FAILURE_WINDOW_SECONDS = 60


class RemoteAccessError(ValueError):
    pass


class RemoteAccessService:
    def __init__(self, state_dir: Path) -> None:
        self._store = RemoteDeviceStore(state_dir)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def start_pairing(self, *, ttl_seconds: int = 300) -> dict[str, str]:
        code = secrets.token_urlsafe(PAIRING_CODE_BYTES)
        expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        self._store.insert_pairing_code(code, expires.isoformat())
        return {"pairing_code": code, "expires_at": expires.isoformat()}

    def ensure_complete_allowed(self, client_key: str) -> None:
        failures = self._store.count_recent_pairing_failures(
            client_key,
            window_seconds=PAIRING_FAILURE_WINDOW_SECONDS,
        )
        if failures >= MAX_PAIRING_FAILURES:
            raise RemoteAccessError("pairing_rate_limited")

    def record_complete_failure(self, client_key: str) -> None:
        self._store.record_pairing_failure(client_key)

    def complete_pairing(self, *, pairing_code: str, device_name: str, client_key: str) -> dict[str, str]:
        if not device_name.strip():
            raise RemoteAccessError("device_name_required")
        self.ensure_complete_allowed(client_key)
        if not self._store.consume_pairing_code(pairing_code):
            self.record_complete_failure(client_key)
            raise RemoteAccessError("invalid_or_expired_pairing_code")
        device_id = secrets.token_urlsafe(16)
        auth_token = secrets.token_urlsafe(32)
        self._store.insert_device(
            device_id=device_id,
            device_name=device_name.strip(),
            token_hash=self._hash_token(auth_token),
        )
        self._store.clear_pairing_failures(client_key)
        return {"device_id": device_id, "auth_token": auth_token}

    def validate_token(self, auth_token: str) -> str | None:
        if not auth_token.strip():
            return None
        return self._store.device_id_for_token_hash(self._hash_token(auth_token.strip()))

    def revoke_device(self, device_id: str) -> bool:
        return self._store.revoke_device(device_id)

    def list_devices(self) -> list[dict[str, str | None]]:
        return self._store.list_devices()
