from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalhostOnlyAction:
    id: str
    method: str
    path_template: str


LOCALHOST_ONLY_ACTION_SPECS: tuple[LocalhostOnlyAction, ...] = (
    # Remote device administration.
    LocalhostOnlyAction("remote.pairing.start", "POST", "/remote/pairing/start"),
    LocalhostOnlyAction("remote.devices.list", "GET", "/remote/devices"),
    LocalhostOnlyAction("remote.devices.delete", "DELETE", "/remote/devices/{device_id}"),
    LocalhostOnlyAction("remote.devices.rotate", "POST", "/remote/devices/{device_id}/rotate"),
    # Workspace / project selection.
    LocalhostOnlyAction("workspaces.upsert", "POST", "/workspaces"),
    LocalhostOnlyAction("workspaces.set_active", "PUT", "/workspaces/active"),
    # Run templates.
    LocalhostOnlyAction("run_templates.create", "POST", "/run-templates"),
    LocalhostOnlyAction("run_templates.update", "PUT", "/run-templates/{template_id}"),
    LocalhostOnlyAction("run_templates.delete", "DELETE", "/run-templates/{template_id}"),
    # Run profiles (provider/model switchboard writes).
    LocalhostOnlyAction("profiles.upsert", "POST", "/profiles"),
    LocalhostOnlyAction("profiles.delete", "DELETE", "/profiles/{name}"),
    LocalhostOnlyAction("projects.bind_profile", "POST", "/projects/{project_path:path}/bind-profile"),
    # Shared capability catalog — skills.
    LocalhostOnlyAction("skills.upsert", "POST", "/skills/{skill_id}"),
    LocalhostOnlyAction("skills.rollback", "POST", "/skills/{skill_id}/rollback"),
    LocalhostOnlyAction("skills.disable", "POST", "/skills/{skill_id}/disable"),
    LocalhostOnlyAction("skills.deprecate", "POST", "/skills/{skill_id}/deprecate"),
    LocalhostOnlyAction("skills.undeprecate", "POST", "/skills/{skill_id}/undeprecate"),
    # Shared capability catalog — MCP servers.
    LocalhostOnlyAction("mcp.upsert", "POST", "/mcp/{server_id}"),
    LocalhostOnlyAction("mcp.rollback", "POST", "/mcp/{server_id}/rollback"),
    LocalhostOnlyAction("mcp.disable", "POST", "/mcp/{server_id}/disable"),
    LocalhostOnlyAction("mcp.deprecate", "POST", "/mcp/{server_id}/deprecate"),
    LocalhostOnlyAction("mcp.undeprecate", "POST", "/mcp/{server_id}/undeprecate"),
    # Harness launch policy. `policy.evaluate` is part of the localhost-only
    # policy editor surface; list it before the `{agent_id}` pattern so it keeps
    # a stable action id instead of being swallowed by the generic match.
    LocalhostOnlyAction("policy.evaluate", "POST", "/policy/evaluate"),
    LocalhostOnlyAction("policy.upsert", "POST", "/policy/{agent_id}"),
    LocalhostOnlyAction("policy.rollback", "POST", "/policy/{agent_id}/rollback"),
    LocalhostOnlyAction("policy.deprecate", "POST", "/policy/{agent_id}/deprecate"),
    LocalhostOnlyAction("policy.undeprecate", "POST", "/policy/{agent_id}/undeprecate"),
    # Catalog surfaces + generic patch rollback.
    LocalhostOnlyAction("catalog.patch", "POST", "/catalog/{harness}/surfaces/patch"),
    LocalhostOnlyAction("patches.rollback", "POST", "/patches/{patch_id}/rollback"),
    # Harness instance registry editor.
    LocalhostOnlyAction("registry.upsert", "POST", "/registry/agents"),
    LocalhostOnlyAction("registry.disable", "POST", "/registry/agents/{agent_id}/disable"),
    # Native harness config editing / repair.
    LocalhostOnlyAction("config.patch", "POST", "/config/{harness_id}/patch"),
    LocalhostOnlyAction("harness_config.patch", "POST", "/harness-config/{harness_id}/patch"),
    # Unified verified-change lifecycle. These routes can mutate every config
    # family above, so they must preserve the same localhost trust boundary.
    LocalhostOnlyAction("changes.preview", "POST", "/changes/preview"),
    LocalhostOnlyAction("changes.apply", "POST", "/changes/{change_id}/apply"),
    LocalhostOnlyAction("changes.rollback", "POST", "/changes/{change_id}/rollback"),
    # Setup import + raw log download.
    LocalhostOnlyAction("setup.import", "POST", "/setup/import"),
    LocalhostOnlyAction("setup.logs_zip", "GET", "/setup/logs.zip"),
)

LOCALHOST_ONLY_ACTIONS: frozenset[str] = frozenset(spec.id for spec in LOCALHOST_ONLY_ACTION_SPECS)

# UI surfaces hidden in remote mode. These mirror the server-side route guard
# above so the web client can hide controls it must not offer remotely; the
# actual boundary is the HTTP route guard, never this list.
UI_LOCALHOST_ONLY_ACTIONS: frozenset[str] = frozenset(
    {
        "ui.write.catalog",
        "ui.write.control-plane",
        "ui.write.harness-config",
        "ui.write.changes",
        "ui.write.profile",
        "ui.write.registry",
        "ui.write.setup-import",
        "ui.download.logs-zip",
        "ui.repair.config",
        "ui.write.workspace",
        "ui.write.run-template",
    }
)


def affordance_localhost_only_actions() -> frozenset[str]:
    return LOCALHOST_ONLY_ACTIONS | UI_LOCALHOST_ONLY_ACTIONS


def _template_to_regex(template: str) -> re.Pattern[str]:
    """Compile a FastAPI-style path template into an anchored regex.

    `{name}` matches a single non-empty path segment; `{name:path}` matches one
    or more segments (FastAPI's ``:path`` converter, e.g. an absolute cwd).
    """
    out: list[str] = []
    for part in re.split(r"(\{[^}]+\})", template):
        if part.startswith("{") and part.endswith("}"):
            out.append(".+" if part[1:-1].endswith(":path") else "[^/]+")
        else:
            out.append(re.escape(part))
    return re.compile("^" + "".join(out) + "$")


_COMPILED_SPECS: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (spec.method, _template_to_regex(spec.path_template), spec.id)
    for spec in LOCALHOST_ONLY_ACTION_SPECS
)


def localhost_only_route_action_id(method: str, path: str) -> str | None:
    for spec_method, pattern, action_id in _COMPILED_SPECS:
        if spec_method == method and pattern.match(path):
            return action_id
    return None


def is_localhost_only_admin_route(method: str, path: str) -> bool:
    return localhost_only_route_action_id(method, path) is not None
