from fastapi import WebSocket
from typing import List

import logging

logger = logging.getLogger("WebSocket")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.MAX_CONNECTIONS = 1 # Strict single-client limit

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        
        # Enforce Limit: Close oldest connection if limit reached
        if len(self.active_connections) >= self.MAX_CONNECTIONS:
            oldest_ws = self.active_connections[0]
            try:
                await oldest_ws.close(code=1000, reason="New connection replaced old one")
                self.active_connections.remove(oldest_ws)
                logger.info("⚠️ Closed old WebSocket connection to accept new one.")
            except Exception as e:
                logger.warning(f"Error closing old WS: {e}")
                if oldest_ws in self.active_connections:
                    self.active_connections.remove(oldest_ws)

        self.active_connections.append(websocket)
        logger.info(f"WebSocket Client Connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket Client Disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        # Filter out closed connections if any
        to_remove = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                # Common error when client disconnects (refresh/close tab)
                # Suppress warning to avoid log spam
                logger.debug(f"Client disconnected during broadcast: {e}")
                to_remove.append(connection)
        
        for conn in to_remove:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

# Global Instance
manager = ConnectionManager()
