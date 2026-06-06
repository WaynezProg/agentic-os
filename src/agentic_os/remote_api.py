from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from agentic_os.audit import AuditEvent, AuditStore
from agentic_os.remote_access import RemoteAccessError, RemoteAccessService

_PAIRING_CLIENTS = {"127.0.0.1", "::1", "testclient"}


class PairingCompleteRequest(BaseModel):
    pairing_code: str
    device_name: str = Field(min_length=1)


def register_remote_routes(
    app: FastAPI,
    *,
    remote: RemoteAccessService,
    audit_store: AuditStore,
) -> None:
    def require_remote_bearer(
        authorization: str | None = Header(default=None),
    ) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing_bearer_token")
        device_id = remote.validate_token(authorization.removeprefix("Bearer ").strip())
        if device_id is None:
            raise HTTPException(status_code=401, detail="invalid_or_revoked_token")
        return device_id

    def require_pairing_access(request: Request) -> None:
        host = request.client.host if request.client else ""
        if host in _PAIRING_CLIENTS:
            return
        if request.headers.get("X-Agentic-OS-Gateway") == "1":
            return
        raise HTTPException(status_code=403, detail="pairing_local_or_gateway_only")

    @app.post("/remote/pairing/start")
    def remote_pairing_start(request: Request) -> dict[str, str]:
        require_pairing_access(request)
        return remote.start_pairing()

    @app.post("/remote/pairing/complete")
    def remote_pairing_complete(
        body: PairingCompleteRequest,
        request: Request,
    ) -> dict[str, str]:
        require_pairing_access(request)
        try:
            return remote.complete_pairing(
                pairing_code=body.pairing_code,
                device_name=body.device_name,
            )
        except RemoteAccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/remote/devices")
    def remote_list_devices(request: Request) -> dict[str, object]:
        require_pairing_access(request)
        return {"devices": remote.list_devices()}

    @app.delete("/remote/devices/{device_id}")
    def remote_revoke_device(device_id: str, request: Request) -> dict[str, bool]:
        require_pairing_access(request)
        revoked = remote.revoke_device(device_id)
        if not revoked:
            raise HTTPException(status_code=404, detail="device_not_found")
        return {"revoked": True}

    @app.get("/events")
    async def events_stream(
        device_id: str = Depends(require_remote_bearer),
        audit: AuditStore = Depends(lambda: audit_store),
    ) -> StreamingResponse:
        async def generate():
            yield ": connected\n\n"
            last_id = 0
            while True:
                rows = audit.list_events_after_id(last_id, domain="config_patch", limit=20)
                for row in rows:
                    last_id = max(last_id, row.id)
                    payload = _audit_event_payload(row, device_id=device_id)
                    yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(generate(), media_type="text/event-stream")


def _audit_event_payload(event: AuditEvent, *, device_id: str) -> dict[str, object]:
    payload = asdict(event)
    payload["remote_device_id"] = device_id
    return payload
