import threading
import logging
import time
import asyncio
from dhan_api_helper import get_dhan_session, fetch_order_list

logger = logging.getLogger("DhanSmartPolling")

class OrderUpdatePoller:
    def __init__(self, client_id, access_token, bot_state, ws_manager=None):
        self.client_id = client_id
        self.access_token = access_token
        self.bot_state = bot_state
        self.ws_manager = ws_manager
        self.is_running = False
        self.thread = None
        self.dhan = None
        self.known_orders = {} # Map OrderId -> Status

    async def connect(self):
        """
        Starts the Polling Loop in a separate thread.
        Async wrapper for API compatibility.
        """
        self.is_running = True
        
        # Initialize Dhan Session
        self.dhan = get_dhan_session()
        if not self.dhan:
            logger.error("Failed to initialize Dhan Session for polling.")
            return

        def run_forever():
            logger.info("🚀 Starting Order Update Polling (Fallback Mode)...")
            while self.is_running:
                try:
                    orders = fetch_order_list(self.dhan)
                    if orders:
                        self.process_orders(orders)
                    else:
                        # If fetch fails, maybe session expired?
                        pass
                        
                except Exception as e:
                    logger.error(f"Polling Error: {e}")
                    # Re-init session if needed
                    # self.dhan = get_dhan_session()
                
                time.sleep(2) # Poll every 2 seconds

        self.thread = threading.Thread(target=run_forever, daemon=True)
        self.thread.start()
        return

    def process_orders(self, orders):
        """
        Compares fetched orders with known state to detect updates.
        """
        for order in orders:
            order_id = order.get('orderId')
            status = order.get('orderStatus')
            
            # If new order or status changed
            if order_id not in self.known_orders or self.known_orders[order_id] != status:
                self.known_orders[order_id] = status
                self.handle_order_update(order)

    def handle_order_update(self, data):
        order_id = data.get("orderId")
        status = data.get("orderStatus")
        symbol = data.get("tradingSymbol")
        
        # logger.info(f"🔔 Order Update (POLL): {symbol} | ID: {order_id} | Status: {status}")
        
        # Update BOT_STATE?
        # Actually, `place_order` updates state initially.
        # We need to find the position matching this order and update it.
        # But unrelated to positions, we might just log it for now.
        
        # If status is TRADED (Filled), likely an entry or exit.
        if status in ["TRADED", "FILLED"]:
             logger.info(f"✅ Order FILLED: {symbol} | {data.get('transactionType')} | Qty: {data.get('quantity')}")
        
        elif status == "REJECTED":
             logger.error(f"❌ Order REJECTED: {symbol} | Reason: {data.get('reasonDescription') or data.get('remarks')}")
             
        elif status == "CANCELLED":
             logger.warning(f"⚠️ Order CANCELLED: {symbol}")

    def stop(self):
        self.is_running = False
