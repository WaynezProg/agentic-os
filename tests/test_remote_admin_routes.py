from __future__ import annotations

from pathlib import Path

import pytest

from agentic_os.remote_affordances import LOCALHOST_ONLY_ACTION_SPECS, LocalhostOnlyAction
from test_api import make_client

# Simulates a request arriving through the remote gateway (i.e. not a direct
# localhost operator). Every localhost-only admin/write route must reject this
# with 403 regardless of bearer token — UI hiding is never the boundary (§2A).
GATEWAY_HEADERS = {"X-Agentic-OS-Gateway": "1"}


def _example_path(template: str) -> str:
    """Materialise a concrete request path from a route template.

    `{name}` -> one segment, `{name:path}` -> a multi-segment value, so the
    gateway middleware's path matching is exercised exactly as in production.
    """
    parts: list[str] = []
    for seg in template.split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            parts.append("sample/nested" if seg[1:-1].endswith(":path") else "sample")
        else:
            parts.append(seg)
    return "/".join(parts)


# Drive coverage off the registry itself: adding a spec automatically adds a
# test case, so a new localhost-only route can never ship unguarded.
@pytest.mark.parametrize("spec", LOCALHOST_ONLY_ACTION_SPECS, ids=lambda spec: spec.id)
def test_localhost_only_route_rejects_gateway_client(
    tmp_path: Path, spec: LocalhostOnlyAction
) -> None:
    client = make_client(tmp_path)
    path = _example_path(spec.path_template)
    # Bodies are irrelevant: the gateway middleware rejects before the handler.
    response = client.request(spec.method, path, headers=GATEWAY_HEADERS, json={})
    assert response.status_code == 403, (
        f"{spec.id} ({spec.method} {path}) reachable via gateway "
        f"(got {response.status_code}); remote write boundary must be server-side"
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/setup/logs.zip"),
        ("POST", "/profiles"),
    ],
)
def test_localhost_only_route_allows_direct_localhost(
    tmp_path: Path, method: str, path: str
) -> None:
    # Same routes, without the gateway header, are NOT blanket-blocked: a direct
    # localhost operator still reaches the handler (any non-403 status is fine).
    client = make_client(tmp_path)
    response = client.request(method, path, json={})
    assert response.status_code != 403
