from __future__ import annotations

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

from agentic_os.remote_affordances import (
    LOCALHOST_ONLY_ACTIONS,
    is_localhost_only_admin_route,
    localhost_only_route_action_id,
)

GATEWAY_HEADER = "X-Agentic-OS-Gateway"
GATEWAY_TRUST_VALUE = "1"
LOCALHOST_CLIENTS = {"127.0.0.1", "::1", "testclient"}


def client_is_localhost(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in LOCALHOST_CLIENTS


def via_trusted_gateway(request: Request) -> bool:
    return request.headers.get(GATEWAY_HEADER) == GATEWAY_TRUST_VALUE


def extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


def is_remote_admin_route(method: str, path: str) -> bool:
    return is_localhost_only_admin_route(method, path)


def is_pairing_complete_route(method: str, path: str) -> bool:
    return method == "POST" and path == "/remote/pairing/complete"


def require_localhost_operator(request: Request) -> None:
    action_id = localhost_only_route_action_id(request.method, request.url.path)
    if action_id is None or action_id not in LOCALHOST_ONLY_ACTIONS:
        raise HTTPException(status_code=500, detail="route_not_localhost_only_action")
    if via_trusted_gateway(request):
        raise HTTPException(status_code=403, detail="remote_admin_localhost_only")
    if not client_is_localhost(request):
        raise HTTPException(status_code=403, detail="remote_admin_localhost_only")


def install_remote_gateway_middleware(app) -> None:
    @app.middleware("http")
    async def remote_gateway_guard(request: Request, call_next):
        from agentic_os.remote_access import RemoteAccessError, RemoteAccessService

        method = request.method
        path = request.url.path
        remote: RemoteAccessService = request.app.state.remote_access

        if is_remote_admin_route(method, path):
            if via_trusted_gateway(request) or not client_is_localhost(request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "remote_admin_localhost_only"},
                )
            return await call_next(request)

        if not via_trusted_gateway(request):
            return await call_next(request)

        if is_pairing_complete_route(method, path):
            client_key = request.client.host if request.client else "unknown"
            try:
                remote.ensure_complete_allowed(client_key)
            except RemoteAccessError as exc:
                if str(exc) == "pairing_rate_limited":
                    return JSONResponse(status_code=429, content={"detail": str(exc)})
                raise
            return await call_next(request)

        token = extract_bearer_token(request)
        device_id = remote.validate_token(token) if token is not None else None
        if device_id is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "missing_or_invalid_bearer_token"},
            )
        request.state.remote_device_id = device_id
        return await call_next(request)
