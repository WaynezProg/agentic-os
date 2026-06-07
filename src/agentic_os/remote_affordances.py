from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalhostOnlyAction:
    id: str
    method: str
    path_template: str


LOCALHOST_ONLY_ACTION_SPECS: tuple[LocalhostOnlyAction, ...] = (
    LocalhostOnlyAction("remote.pairing.start", "POST", "/remote/pairing/start"),
    LocalhostOnlyAction("remote.devices.list", "GET", "/remote/devices"),
    LocalhostOnlyAction("remote.devices.delete", "DELETE", "/remote/devices/{device_id}"),
    LocalhostOnlyAction("remote.devices.rotate", "POST", "/remote/devices/{device_id}/rotate"),
)

LOCALHOST_ONLY_ACTIONS: frozenset[str] = frozenset(spec.id for spec in LOCALHOST_ONLY_ACTION_SPECS)


def localhost_only_route_action_id(method: str, path: str) -> str | None:
    for spec in LOCALHOST_ONLY_ACTION_SPECS:
        if spec.method == method and _path_matches_template(path, spec.path_template):
            return spec.id
    return None


def is_localhost_only_admin_route(method: str, path: str) -> bool:
    return localhost_only_route_action_id(method, path) is not None


def _path_matches_template(path: str, template: str) -> bool:
    if template == "/remote/pairing/start":
        return path == template
    if template == "/remote/devices":
        return path == template
    if template == "/remote/devices/{device_id}":
        prefix = "/remote/devices/"
        return path.startswith(prefix) and len(path) > len(prefix)
    if template == "/remote/devices/{device_id}/rotate":
        prefix = "/remote/devices/"
        suffix = "/rotate"
        return path.startswith(prefix) and path.endswith(suffix) and len(path) > len(prefix) + len(suffix)
    return False
