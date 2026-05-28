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

    def get_session_events(self, session_id: str) -> dict[str, Any]:
        return self._get(f"/sessions/{_validate_path_id(session_id)}/events")

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

    def summarize_session(self, session_id: str) -> dict[str, Any]:
        return self._post(f"/sessions/{_validate_path_id(session_id)}/memory/summary", {})

    def show_session_summary(self, session_id: str) -> dict[str, Any]:
        return self._get(f"/sessions/{_validate_path_id(session_id)}/memory/summary")

    def create_memory_review(self, session_id: str) -> dict[str, Any]:
        return self._post(f"/sessions/{_validate_path_id(session_id)}/memory/review", {})

    def list_memory_review(self) -> dict[str, Any]:
        return self._get("/memory/review")

    def approve_memory_review(self, item_id: str) -> dict[str, Any]:
        return self._post(f"/memory/review/{_validate_path_id(item_id)}/approve", {})

    def reject_memory_review(self, item_id: str) -> dict[str, Any]:
        return self._post(f"/memory/review/{_validate_path_id(item_id)}/reject", {})

    def list_memories(self) -> dict[str, Any]:
        return self._get("/memory")

    def search_memories(self, query: str) -> dict[str, Any]:
        return self._get("/memory/search", params={"q": query})

    def list_skills(self) -> dict[str, Any]:
        return self._get("/skills")

    def show_skill(self, skill_id: str) -> dict[str, Any]:
        return self._get(f"/skills/{_validate_path_id(skill_id)}")

    def upsert_skill(self, skill_id: str, payload: dict[str, object]) -> dict[str, Any]:
        return self._post(f"/skills/{_validate_path_id(skill_id)}", payload)

    def disable_skill(self, skill_id: str) -> dict[str, Any]:
        return self._post(f"/skills/{_validate_path_id(skill_id)}/disable", {})

    def list_mcp_servers(self) -> dict[str, Any]:
        return self._get("/mcp")

    def show_mcp_server(self, server_id: str) -> dict[str, Any]:
        return self._get(f"/mcp/{_validate_path_id(server_id)}")

    def upsert_mcp_server(self, server_id: str, payload: dict[str, object]) -> dict[str, Any]:
        return self._post(f"/mcp/{_validate_path_id(server_id)}", payload)

    def disable_mcp_server(self, server_id: str) -> dict[str, Any]:
        return self._post(f"/mcp/{_validate_path_id(server_id)}/disable", {})

    def list_policies(self) -> dict[str, Any]:
        return self._get("/policy")

    def show_policy(self, agent_id: str) -> dict[str, Any]:
        return self._get(f"/policy/{_validate_path_id(agent_id)}")

    def upsert_policy(self, agent_id: str, payload: dict[str, object]) -> dict[str, Any]:
        return self._post(f"/policy/{_validate_path_id(agent_id)}", payload)

    def evaluate_policy(self, payload: dict[str, object]) -> dict[str, Any]:
        return self._post("/policy/evaluate", payload)

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
