from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx


_PATH_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]+")


class AgenticClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def list_agents(self) -> dict[str, Any]:
        return self._get("/agents")

    def show_agent(self, agent_id: str) -> dict[str, Any]:
        return self._get(f"/agents/{_validate_path_id(agent_id)}")

    def run_session(
        self,
        agent_id: str,
        cwd: str | None,
        message: str,
        profile: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, object] = {
            "agent_id": agent_id,
            "cwd": cwd,
            "message": message,
        }
        if profile is not None:
            payload["profile"] = profile
        return self._post("/sessions", payload)

    def list_sessions(self) -> dict[str, Any]:
        return self._get("/sessions")

    def show_session(self, session_id: str) -> dict[str, Any]:
        return self._get(f"/sessions/{_validate_path_id(session_id)}")

    def get_session_events(self, session_id: str) -> dict[str, Any]:
        return self._get(f"/sessions/{_validate_path_id(session_id)}/events")

    def get_session_evidence(self, session_id: str) -> dict[str, Any]:
        return self._get(f"/sessions/{_validate_path_id(session_id)}/evidence")

    def get_session_evidence_events(
        self,
        session_id: str,
        after: int = 0,
        max_lines: int = 5000,
    ) -> dict[str, Any]:
        return self._get(
            f"/sessions/{_validate_path_id(session_id)}/evidence/events",
            params={"after": after, "max_lines": max_lines},
        )

    def get_session_timeline(
        self,
        session_id: str,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, object] = {}
        if event_type is not None:
            params["event_type"] = event_type
        return self._get(f"/sessions/{_validate_path_id(session_id)}/timeline", params=params)

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

    def attach_session(self, session_id: str, mode: str = "preview") -> dict[str, Any]:
        return self._post(
            f"/sessions/{_validate_path_id(session_id)}/attach",
            {"mode": mode},
        )

    def list_approvals(
        self,
        status: str | None = None,
        harness_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        params: dict[str, object] = {"limit": limit}
        if status:
            params["status"] = status
        if harness_id:
            params["harness_id"] = harness_id
        return self._get("/approvals", params=params)

    def show_approval(self, approval_id: str) -> dict[str, Any]:
        return self._get(f"/approvals/{_validate_path_id(approval_id)}")

    def approve_approval(self, approval_id: str) -> dict[str, Any]:
        return self._post(f"/approvals/{_validate_path_id(approval_id)}/approve", {})

    def reject_approval(self, approval_id: str, reason: str = "") -> dict[str, Any]:
        return self._post(
            f"/approvals/{_validate_path_id(approval_id)}/reject",
            {"reason": reason},
        )

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

    def fleet_health(self) -> dict[str, Any]:
        return self._get("/fleet/health")

    def fleet_instance_health(self, agent_id: str) -> dict[str, Any]:
        return self._get(f"/fleet/{_validate_path_id(agent_id)}/health")

    def fleet_events(
        self,
        agent_id: str | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, object] = {}
        if agent_id is not None:
            params["agent_id"] = agent_id
        if event_type is not None:
            params["event_type"] = event_type
        return self._get("/fleet/events", params=params)

    def fleet_capacity(self) -> dict[str, Any]:
        return self._get("/fleet/capacity")

    def fleet_probe(self) -> dict[str, Any]:
        return self._post("/fleet/probe", {})

    def deprecate_skill(
        self,
        skill_id: str,
        *,
        reason: str = "",
        replacement_id: str | None = None,
        sunset_at: str | None = None,
    ) -> dict[str, Any]:
        return self._post(
            f"/skills/{_validate_path_id(skill_id)}/deprecate",
            _deprecation_payload(reason, replacement_id, sunset_at),
        )

    def undeprecate_skill(self, skill_id: str) -> dict[str, Any]:
        return self._post(f"/skills/{_validate_path_id(skill_id)}/undeprecate", {})

    def deprecate_mcp_server(
        self,
        server_id: str,
        *,
        reason: str = "",
        replacement_id: str | None = None,
        sunset_at: str | None = None,
    ) -> dict[str, Any]:
        return self._post(
            f"/mcp/{_validate_path_id(server_id)}/deprecate",
            _deprecation_payload(reason, replacement_id, sunset_at),
        )

    def undeprecate_mcp_server(self, server_id: str) -> dict[str, Any]:
        return self._post(f"/mcp/{_validate_path_id(server_id)}/undeprecate", {})

    def deprecate_policy(
        self,
        agent_id: str,
        *,
        reason: str = "",
        replacement_id: str | None = None,
        sunset_at: str | None = None,
    ) -> dict[str, Any]:
        return self._post(
            f"/policy/{_validate_path_id(agent_id)}/deprecate",
            _deprecation_payload(reason, replacement_id, sunset_at),
        )

    def undeprecate_policy(self, agent_id: str) -> dict[str, Any]:
        return self._post(f"/policy/{_validate_path_id(agent_id)}/undeprecate", {})

    def audit_events(
        self,
        domain: str | None = None,
        entity_id: str | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        params: dict[str, object] = {"limit": limit}
        if domain is not None:
            params["domain"] = domain
        if entity_id is not None:
            params["entity_id"] = entity_id
        if event_type is not None:
            params["event_type"] = event_type
        return self._get("/audit/events", params=params)

    def audit_policy_coverage(self) -> dict[str, Any]:
        return self._get("/audit/policy-coverage")

    def diagnostics_resources(self) -> dict[str, Any]:
        return self._get("/diagnostics/resources")

    def list_harnesses(self) -> dict[str, Any]:
        return self._get("/harnesses")

    def harnesses_validate(self) -> dict[str, Any]:
        return self._get("/harnesses/validate")

    def show_harness(self, harness_id: str) -> dict[str, Any]:
        return self._get(f"/harnesses/{_validate_path_id(harness_id)}")

    def harness_health(self, harness_id: str) -> dict[str, Any]:
        return self._get(f"/harnesses/{_validate_path_id(harness_id)}/health")

    def harness_logs(self, harness_id: str) -> dict[str, Any]:
        return self._get(f"/harnesses/{_validate_path_id(harness_id)}/logs")

    def harness_activity(self, harness_id: str, event_type: str | None = None) -> dict[str, Any]:
        params: dict[str, object] = {}
        if event_type:
            params["event_type"] = event_type
        return self._get(f"/harnesses/{_validate_path_id(harness_id)}/activity", params=params)

    def list_harness_contracts(self, version: str = "v1") -> dict[str, Any]:
        return self._get("/harness-contracts", params={"version": version})

    def show_harness_contract(self, harness_id: str, version: str = "v1") -> dict[str, Any]:
        return self._get(
            f"/harness-contracts/{_validate_path_id(harness_id)}",
            params={"version": version},
        )

    def list_profiles(self, cwd: str | None = None) -> dict[str, Any]:
        params: dict[str, object] = {}
        if cwd is not None:
            params["cwd"] = cwd
        return self._get("/profiles", params=params)

    def show_profile(self, name: str) -> dict[str, Any]:
        return self._get(f"/profiles/{_validate_path_id(name)}")

    def upsert_profile(
        self,
        profile: dict[str, Any],
        *,
        scope: str = "local",
        cwd: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, object] = {"scope": scope}
        if cwd is not None:
            params["cwd"] = cwd
        return self._post("/profiles", profile, params=params)

    def bind_project_profile(self, project_path: str, run_profile: str) -> dict[str, Any]:
        encoded_path = quote(project_path, safe="")
        return self._post(
            f"/projects/{encoded_path}/bind-profile",
            {"run_profile": run_profile},
        )

    def usage_summary(
        self,
        *,
        from_: str | None = None,
        to: str | None = None,
        harness_id: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        params = {
            key: value
            for key, value in {
                "from": from_,
                "to": to,
                "harness_id": harness_id,
                "provider": provider,
            }.items()
            if value is not None
        }
        return self._get("/usage/summary", params=params)

    def usage_session(self, session_id: str) -> dict[str, Any]:
        return self._get(f"/usage/sessions/{_validate_path_id(session_id)}")

    def usage_quotas(self, scope: str = "daily", *, cwd: str | None = None) -> dict[str, Any]:
        params: dict[str, object] = {"scope": scope}
        if cwd is not None:
            params["cwd"] = cwd
        return self._get("/usage/quotas", params=params)

    def catalog_surfaces(
        self,
        harness: str,
        cwd: str | None = None,
        scope: str | None = None,
        surface_type: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, object] = {}
        if cwd:
            params["cwd"] = cwd
        if scope:
            params["scope"] = scope
        if surface_type:
            params["surface_type"] = surface_type
        return self._get(f"/catalog/{_validate_path_id(harness)}/surfaces", params=params)

    def catalog_merged(self, harness: str, cwd: str | None = None) -> dict[str, Any]:
        params: dict[str, object] = {}
        if cwd:
            params["cwd"] = cwd
        return self._get(f"/catalog/{_validate_path_id(harness)}/merged", params=params)

    def catalog_diff(
        self,
        harness: str,
        cwd_a: str | None = None,
        cwd_b: str | None = None,
        scope_a: str | None = None,
        scope_b: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, object] = {}
        if cwd_a:
            params["cwd_a"] = cwd_a
        if cwd_b:
            params["cwd_b"] = cwd_b
        if scope_a:
            params["scope_a"] = scope_a
        if scope_b:
            params["scope_b"] = scope_b
        return self._get(f"/catalog/{_validate_path_id(harness)}/diff", params=params)

    def catalog_patch(
        self,
        harness: str,
        ops: list[dict[str, object]],
        *,
        cwd: str | None = None,
        dry_run: bool = False,
        source: str = "cli",
    ) -> dict[str, Any]:
        params: dict[str, object] = {}
        if cwd is not None:
            params["cwd"] = cwd
        if dry_run:
            params["dry_run"] = True
        return self._post(
            f"/catalog/{_validate_path_id(harness)}/surfaces/patch",
            {"ops": ops, "source": source},
            params=params or None,
        )

    def patches_list(
        self,
        harness: str | None = None,
        cwd: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, object] = {"limit": limit}
        if harness is not None:
            params["harness"] = harness
        if cwd is not None:
            params["cwd"] = cwd
        return self._get("/patches", params=params)

    def patches_show(self, patch_id: str) -> dict[str, Any]:
        return self._get(f"/patches/{_validate_path_id(patch_id)}")

    def patches_rollback(self, patch_id: str, *, source: str = "cli") -> dict[str, Any]:
        return self._post(
            f"/patches/{_validate_path_id(patch_id)}/rollback",
            {},
            params={"source": source},
        )

    def config_effective(self, harness_id: str, cwd: str | None = None) -> dict[str, Any]:
        params: dict[str, object] = {}
        if cwd:
            params["cwd"] = cwd
        return self._get(f"/config/{_validate_path_id(harness_id)}/effective", params=params)

    def config_diff(
        self,
        harness_id: str,
        scope_a: str = "user",
        scope_b: str = "project",
        cwd: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, object] = {"scope_a": scope_a, "scope_b": scope_b}
        if cwd:
            params["cwd"] = cwd
        return self._get(f"/config/{_validate_path_id(harness_id)}/diff", params=params)

    def config_explain(self, harness_id: str, cwd: str | None = None) -> dict[str, Any]:
        params: dict[str, object] = {}
        if cwd:
            params["cwd"] = cwd
        return self._get(f"/config/{_validate_path_id(harness_id)}/explain", params=params)

    def harness_config_effective(self, harness_id: str, cwd: str | None = None) -> dict[str, Any]:
        params: dict[str, object] = {}
        if cwd:
            params["cwd"] = cwd
        return self._get(
            f"/harness-config/{_validate_path_id(harness_id)}/effective",
            params=params,
        )

    def harness_config_diff(
        self,
        harness_id: str,
        scope_a: str = "user",
        scope_b: str = "project",
        cwd: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, object] = {"scope_a": scope_a, "scope_b": scope_b}
        if cwd:
            params["cwd"] = cwd
        return self._get(
            f"/harness-config/{_validate_path_id(harness_id)}/diff",
            params=params,
        )

    def harness_config_explain(self, harness_id: str, cwd: str | None = None) -> dict[str, Any]:
        params: dict[str, object] = {}
        if cwd:
            params["cwd"] = cwd
        return self._get(
            f"/harness-config/{_validate_path_id(harness_id)}/explain",
            params=params,
        )

    def _get(self, path: str, params: dict[str, object] | None = None) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            response = client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    def _post(
        self,
        path: str,
        payload: dict[str, object],
        params: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            post_kwargs: dict[str, object] = {"json": payload}
            if params is not None:
                post_kwargs["params"] = params
            response = client.post(path, **post_kwargs)
            response.raise_for_status()
            return response.json()


def _validate_path_id(value: str) -> str:
    if not _PATH_ID_PATTERN.fullmatch(value):
        raise ValueError("unsafe path id")
    return value


def _deprecation_payload(
    reason: str,
    replacement_id: str | None,
    sunset_at: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if reason:
        payload["reason"] = reason
    if replacement_id is not None:
        payload["replacement_id"] = replacement_id
    if sunset_at is not None:
        payload["sunset_at"] = sunset_at
    return payload
