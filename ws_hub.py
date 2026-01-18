from fastapi import WebSocket
from typing import List

import logging

logger = logging.getLogger("WebSocket")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket Client Connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket Client Disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        # Filter out closed connections if any
        to_remove = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Error sending to WS client: {e}")
                to_remove.append(connection)
        
        for conn in to_remove:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

# Global Instance
manager = ConnectionManager()
