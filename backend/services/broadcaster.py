import json
import logging
from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._authorization = {}

    async def connect(self, ws: WebSocket, authorized=None) -> None:
        await ws.accept()
        self._connections.append(ws)
        self._authorization[ws] = authorized
        log.info(f"WS client connected — total: {len(self._connections)}")

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        self._authorization.pop(ws, None)
        log.info(f"WS client disconnected — total: {len(self._connections)}")

    async def broadcast(self, payload: dict) -> None:
        dead = []
        for ws in list(self._connections):
            try:
                authorized = self._authorization.get(ws)
                if authorized and not await authorized():
                    await ws.close(code=1008)
                    dead.append(ws)
                    continue
                await ws.send_text(json.dumps(payload, default=str))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


broadcaster = ConnectionManager()
