from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, Field

from agentic_os.control_plane import (
    ControlPlaneStore,
    PolicyEvaluationRequest,
    PolicyEvaluationResult,
)

SESSION_START_TOOL = "session.start"
Decision = Literal["allow", "deny", "approval_required"]


class LaunchContext(BaseModel):
    agent_id: str
    cwd: str | None = None
    model_id: str | None = None
    skill_id: str | None = None
    mcp_server_id: str | None = None
    tool_name: str | None = None
    running_sessions: int = 0
    max_running_sessions: int = 50
    check_capacity: bool = True
    for_session_start: bool = True
    require_policy: bool = False
    approval_granted: bool = False


class LaunchDecision(BaseModel):
    agent_id: str
    decision: Decision
    reason: str
    detail: str
    warnings: list[str] = Field(default_factory=list)
    policy_present: bool
    readonly: bool = False
    rate_limit_per_minute: int | None = None
    policy_result: dict[str, object] | None = None

    def to_policy_result(self) -> PolicyEvaluationResult:
        return PolicyEvaluationResult(
            agent_id=self.agent_id,
            decision=self.decision,
            reason=self.detail,
            readonly=self.readonly,
            rate_limit_per_minute=self.rate_limit_per_minute,
            warnings=list(self.warnings),
        )


class LaunchDecisionService:
    def __init__(self, control_plane: ControlPlaneStore) -> None:
        self.control_plane = control_plane

    def evaluate(self, context: LaunchContext) -> LaunchDecision:
        if (
            context.check_capacity
            and context.running_sessions >= context.max_running_sessions
        ):
            return LaunchDecision(
                agent_id=context.agent_id,
                decision="deny",
                reason="capacity_limit_reached",
                detail=(
                    f"Capacity limit reached: {context.running_sessions}/"
                    f"{context.max_running_sessions} concurrent sessions"
                ),
                policy_present=self._policy_present(context.agent_id),
            )

        try:
            policy = self.control_plane.get_policy(context.agent_id)
        except (KeyError, ValueError):
            if context.require_policy:
                return LaunchDecision(
                    agent_id=context.agent_id,
                    decision="deny",
                    reason="policy_missing",
                    detail=f"no policy configured for {context.agent_id}",
                    policy_present=False,
                )
            return LaunchDecision(
                agent_id=context.agent_id,
                decision="allow",
                reason="policy_missing_open_default",
                detail=f"no policy configured for {context.agent_id}",
                warnings=["no launch policy configured"],
                policy_present=False,
            )

        result = self.control_plane.evaluate_policy(
            PolicyEvaluationRequest(
                agent_id=context.agent_id,
                skill_id=context.skill_id,
                mcp_server_id=context.mcp_server_id,
                tool_name=context.tool_name,
                model_id=context.model_id,
                cwd=context.cwd,
            )
        )
        decision = result.decision
        detail = result.reason
        reason = {
            "allow": "policy_allowed",
            "deny": "policy_denied",
            "approval_required": "approval_required",
        }[decision]

        if (
            decision == "allow"
            and context.for_session_start
            and self._requires_session_start_approval(
                policy.approval_required_tool_names
            )
        ):
            decision = "approval_required"
            reason = "approval_required"
            detail = f"{SESSION_START_TOOL} requires approval for {context.agent_id}"

        if decision == "approval_required" and context.approval_granted:
            decision = "allow"
            reason = "approval_granted"
            detail = f"approval granted for {context.agent_id}"

        return LaunchDecision(
            agent_id=context.agent_id,
            decision=decision,
            reason=reason,
            detail=detail,
            warnings=list(result.warnings),
            policy_present=True,
            readonly=result.readonly,
            rate_limit_per_minute=result.rate_limit_per_minute,
            policy_result=asdict(result),
        )

    def _policy_present(self, agent_id: str) -> bool:
        try:
            self.control_plane.get_policy(agent_id)
        except (KeyError, ValueError):
            return False
        return True

    @staticmethod
    def _requires_session_start_approval(tool_names: list[str]) -> bool:
        return "*" in tool_names or SESSION_START_TOOL in tool_names
