import asyncio
import websockets
import json
import logging
import ssl

logger = logging.getLogger("DhanSmartWS")

class OrderUpdateWS:
    def __init__(self, client_id, access_token, bot_state, ws_manager=None):
        self.url = "wss://api-order-update.dhan.co"
        self.client_id = client_id
        self.access_token = access_token
        self.bot_state = bot_state  # Reference to shared state
        self.ws_manager = ws_manager  # To broadcast updates
        self.ws = None
        self.is_running = False

    async def connect(self):
        """
        Connects and listens to the Dhan Signal WebSocket.
        """
        self.is_running = True
        logger.info(f"🔄 Connecting to Dhan WebSocket: {self.url}")

        while self.is_running:
            try:
                # SSL Context for secure wss
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

                async with websockets.connect(self.url, ssl=ssl_context) as websocket:
                    self.ws = websocket
                    logger.info("✅ Connected to Dhan WebSocket")

                    # 1. Send Authorization Packet
                    auth_packet = {
                        "LoginReq": {
                            "MsgCode": 42,
                            "ClientId": str(self.client_id),
                            "Token": str(self.access_token)
                        },
                        "UserType": "SELF"
                    }
                    await websocket.send(json.dumps(auth_packet))
                    logger.info("📤 Sent Auth Packet")

                    # 2. Listen for Messages
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            await self.process_message(data)
                        except json.JSONDecodeError:
                            logger.error(f"❌ JSON Decode Error: {message}")
                        except Exception as e:
                            logger.error(f"❌ Error processing message: {e}")

            except Exception as e:
                logger.error(f"🔌 WebSocket Disconnected: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def process_message(self, data):
        """
        Processes incoming Order Update packets.
        """
        msg_type = data.get("Type")

        if msg_type == "order_alert":
            order_data = data.get("Data", {})
            self.handle_order_update(order_data)
        else:
            # Heartbeats or other messages
            pass

    def handle_order_update(self, data):
        """
        Updates Bot State based on Order Updates.
        Dhan Status: TRANSIT, PENDING, REJECTED, CANCELLED, TRADED, EXPIRED
        """
        order_id = data.get("OrderNo")
        status = data.get("Status")  # Dhan Status
        symbol = data.get("TradingSymbol") or data.get("DisplayName") # Fallback
        
        # Determine internal status
        internal_status = "UNKNOWN"
        if status in ["TRADED"]:
            internal_status = "FILLED"
        elif status in ["PENDING", "TRANSIT"]:
            internal_status = "PENDING"
        elif status in ["CANCELLED"]:
            internal_status = "CANCELLED"
        elif status in ["REJECTED"]:
            internal_status = "REJECTED"

        logger.info(f"🔔 Order Update: {symbol} | ID: {order_id} | Status: {status} -> {internal_status}")

        if not self.bot_state:
            return

        # Update Shared State
        # Find position/order by order ID if possible, or symbol
        # For now, simple logging and partial state update
        
        # Example: Update positions if TRADED
        if internal_status == "FILLED":
            # Logic to update self.bot_state['positions'] would go here
            # But state reconciliation usually handles this via polling too.
            # This ensures fast UI updates.
            pass

        # Broadcast if Manager is available
        if self.ws_manager:
            # We construct a simple event to push to frontend
            event = {
                "type": "ORDER_UPDATE",
                "data": {
                    "order_id": order_id,
                    "status": internal_status,
                    "symbol": symbol,
                    "price": data.get("Price"),
                    "filled_qty": data.get("TradedQty")
                }
            }
            # Fire and forget (needs async loop handling in real app)
            # await self.ws_manager.broadcast(event) 
            logger.info("Broadcasting Order Update (Mock)")

    def stop(self):
        self.is_running = False
        if self.ws:
            asyncio.create_task(self.ws.close())
