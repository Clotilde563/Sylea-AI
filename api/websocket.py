"""WebSocket manager for real-time communication with desktop app."""
from __future__ import annotations

import uuid

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections per user."""

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        if user_id in self.active_connections:
            self.active_connections[user_id] = [
                ws for ws in self.active_connections[user_id] if ws != websocket
            ]
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_to_user(self, user_id: str, message: dict) -> None:
        """Send a message to all desktop connections for a user."""
        if user_id in self.active_connections:
            for ws in self.active_connections[user_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

    def is_connected(self, user_id: str) -> bool:
        return user_id in self.active_connections and len(self.active_connections[user_id]) > 0

    async def request_file_read(self, user_id: str, path: str, timeout: float = 10.0) -> dict:
        """Demande au desktop de lire un fichier et attend la reponse."""
        if not self.is_connected(user_id):
            return {"success": False, "error": "Desktop non connecte"}

        request_id = str(uuid.uuid4())
        # Envoyer la requete
        await self.send_to_user(user_id, {
            "type": "file_read_request",
            "path": path,
            "request_id": request_id,
        })
        # Note: la reponse sera traitee cote client (Tauri) et renvoyee
        # via un POST /api/agent3/file-response ou un autre message WS.
        # Pour l'instant on retourne un flag "requested"
        return {"success": True, "requested": True, "request_id": request_id}


# Global instance
ws_manager = ConnectionManager()
