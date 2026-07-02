from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from backend.services.broadcaster import broadcaster

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await broadcaster.connect(ws)
    try:
        while True:
            # Keep connection alive; we only push, never receive
            await ws.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(ws)
