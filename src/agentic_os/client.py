from __future__ import annotations

import re
from typing import Any

import httpx


_PATH_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]+")


class AgenticClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def list_agents(self) -> dict[str, Any]:
        return self._get("/agents")

    def show_agent(self, agent_id: str) -> dict[str, Any]:
        return self._get(f"/agents/{_validate_path_id(agent_id)}")

    def run_session(self, agent_id: str, cwd: str | None, message: str) -> dict[str, Any]:
        return self._post("/sessions", {"agent_id": agent_id, "cwd": cwd, "message": message})

    def list_sessions(self) -> dict[str, Any]:
        return self._get("/sessions")

    def show_session(self, session_id: str) -> dict[str, Any]:
        return self._get(f"/sessions/{_validate_path_id(session_id)}")

    def get_logs(
        self,
        session_id: str,
        stream: str | None = None,
        after: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, object] = {"after": after}
        if stream is not None:
            params["stream"] = stream
        return self._get(f"/sessions/{_validate_path_id(session_id)}/logs", params=params)

    def stop_session(self, session_id: str) -> dict[str, Any]:
        return self._post(f"/sessions/{_validate_path_id(session_id)}/stop", {})

    def retry_session(self, session_id: str) -> dict[str, Any]:
        return self._post(f"/sessions/{_validate_path_id(session_id)}/retry", {})

    def _get(self, path: str, params: dict[str, object] | None = None) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            response = client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            response = client.post(path, json=payload)
            response.raise_for_status()
            return response.json()


def _validate_path_id(value: str) -> str:
    if not _PATH_ID_PATTERN.fullmatch(value):
        raise ValueError("unsafe path id")
    return value
