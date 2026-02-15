import threading
import logging
import time
import asyncio
from dhanhq import DhanContext, OrderUpdate
from config import config_manager

logger = logging.getLogger("DhanSmartWS")

class OrderUpdateWS:
    def __init__(self, client_id, access_token, bot_state, ws_manager=None):
        self.client_id = client_id
        self.access_token = access_token
        self.bot_state = bot_state
        self.ws_manager = ws_manager
        self.is_running = False
        self.thread = None
        self.dhan_context = None
        self.order_client = None

    def on_order_update(self, order_data):
        """Callback function to process order update data"""
        try:
            # The library returns a dict, likely with "Data" key based on documentation
            # But the user snippet said: print(order_data["Data"])
            # Let's handle both cases safely
            data = order_data.get("Data", order_data)
            self.handle_order_update(data)
            
            # Optional: Update Heartbeat for monitoring (even if not critical)
            if self.bot_state:
                self.bot_state.setdefault("heartbeat", {})["websocket"] = time.time()
        except Exception as e:
            logger.error(f"❌ Error processing order update: {e}")

    def handle_order_update(self, data):
        """Log order updates similar to the poller"""
        order_id = data.get("OrderNo") or data.get("orderId")
        status = data.get("Status") or data.get("orderStatus")
        symbol = data.get("TradingSymbol") or data.get("tradingSymbol") or data.get("DisplayName")
        
        if status in ["TRADED", "FILLED"]:
             logger.info(f"✅ Order FILLED (WS): {symbol} | ID: {order_id} | Status: {status}")
        elif status == "REJECTED":
             reason = data.get("Reason") or data.get("reasonDescription") or "Unknown"
             logger.error(f"❌ Order REJECTED (WS): {symbol} | Reason: {reason}")
        elif status == "CANCELLED":
             logger.warning(f"⚠️ Order CANCELLED (WS): {symbol}")
        elif status == "PENDING":
             logger.info(f"⏳ Order PENDING (WS): {symbol} | ID: {order_id}")

    async def connect(self):
        """
        Starts the WebSocket connection in a separate thread.
        Async wrapper for API compatibility.
        """
        self.is_running = True
        
        # Initialize Dhan Context
        try:
             self.dhan_context = DhanContext(self.client_id, self.access_token)
             self.order_client = OrderUpdate(self.dhan_context)
             self.order_client.on_update = self.on_order_update
        except Exception as e:
             logger.error(f"❌ Failed to initialize DhanContext: {e}")
             return

        def run_forever():
            logger.info("🚀 Starting Dhan Order Update WebSocket (Official Lib)...")
            while self.is_running:
                try:
                    self.order_client.connect_to_dhan_websocket_sync()
                except Exception as e:
                    logger.error(f"⚠️ Dhan WebSocket Connection Error: {e}")
                    logger.info("🔄 Reconnecting in 5s...")
                    time.sleep(5)

        self.thread = threading.Thread(target=run_forever, daemon=True)
        self.thread.start()
        return

    async def connect_async(self):
        """Alias for compatibility"""
        await self.connect()

    def stop(self):
        self.is_running = False
        # The library might not have a clean stop method exposed easily in sync mode 
        # but setting is_running=False stops the reconnection loop.

