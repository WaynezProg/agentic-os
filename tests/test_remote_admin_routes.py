from __future__ import annotations

from pathlib import Path

import pytest

from test_api import make_client

# Simulates a request arriving through the remote gateway (i.e. not a direct
# localhost operator). Every localhost-only admin/write route must reject this
# with 403 regardless of bearer token — UI hiding is never the boundary (§2A).
GATEWAY_HEADERS = {"X-Agentic-OS-Gateway": "1"}

# (method, path) for representative write surfaces that the UI marks
# localhost-only. Bodies are irrelevant: the gateway middleware rejects before
# the route handler runs.
LOCALHOST_ONLY_WRITE_ROUTES: list[tuple[str, str]] = [
    ("POST", "/profiles"),
    ("DELETE", "/profiles/sample"),
    ("POST", "/projects/repo/bind-profile"),
    ("POST", "/skills/sample"),
    ("POST", "/skills/sample/rollback"),
    ("POST", "/skills/sample/disable"),
    ("POST", "/skills/sample/deprecate"),
    ("POST", "/skills/sample/undeprecate"),
    ("POST", "/mcp/sample"),
    ("POST", "/mcp/sample/rollback"),
    ("POST", "/mcp/sample/disable"),
    ("POST", "/mcp/sample/deprecate"),
    ("POST", "/mcp/sample/undeprecate"),
    ("POST", "/policy/sample"),
    ("POST", "/policy/sample/rollback"),
    ("POST", "/policy/sample/deprecate"),
    ("POST", "/policy/sample/undeprecate"),
    ("POST", "/policy/evaluate"),
    ("POST", "/catalog/sample/surfaces/patch"),
    ("POST", "/patches/sample/rollback"),
    ("POST", "/registry/agents"),
    ("POST", "/registry/agents/sample/disable"),
    ("POST", "/config/sample/patch"),
    ("POST", "/harness-config/sample/patch"),
    ("POST", "/setup/import"),
    ("GET", "/setup/logs.zip"),
]


@pytest.mark.parametrize("method,path", LOCALHOST_ONLY_WRITE_ROUTES)
def test_localhost_only_write_route_rejects_gateway_client(
    tmp_path: Path, method: str, path: str
) -> None:
    client = make_client(tmp_path)
    response = client.request(method, path, headers=GATEWAY_HEADERS, json={})
    assert response.status_code == 403, (
        f"{method} {path} reachable via gateway (got {response.status_code}); "
        "remote write boundary must be server-side"
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/setup/logs.zip"),
        ("POST", "/profiles"),
    ],
)
def test_localhost_only_write_route_allows_direct_localhost(
    tmp_path: Path, method: str, path: str
) -> None:
    # Same routes, without the gateway header, are NOT blanket-blocked: a direct
    # localhost operator still reaches the handler (any non-403 status is fine).
    client = make_client(tmp_path)
    response = client.request(method, path, json={})
    assert response.status_code != 403
