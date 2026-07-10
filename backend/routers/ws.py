from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from backend.auth import _verify_token
from backend.services.broadcaster import broadcaster

router = APIRouter()

_ALLOWED_ORIGINS = {"http://localhost:3000", "http://localhost:3001"}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    origin = ws.headers.get("origin")
    if origin and origin not in _ALLOWED_ORIGINS:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    token = ws.query_params.get("token", "")
    if not token or not _verify_token(token):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await broadcaster.connect(ws)
    try:
        while True:
            # Keep connection alive; we only push, never receive.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.disconnect(ws)
