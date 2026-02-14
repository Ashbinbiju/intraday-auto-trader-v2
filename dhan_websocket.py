"""
Dhan Order WebSocket Handler
Handles real-time order updates via Dhan's WebSocket API
"""
import logging
import threading
import time
from dhanhq import DhanContext, OrderUpdate
from config import config_manager
from state_manager import state_lock

logger = logging.getLogger("DhanOrderSocket")

def start_dhan_websocket(bot_state):
    """
    Start Dhan Order Update WebSocket using official DhanHQ SDK.
    Updates BOT_STATE with real-time order status.
    """
    client_id = config_manager.get("credentials", "dhan_client_id")
    access_token = config_manager.get("credentials", "dhan_access_token")
    
    if not client_id or not access_token:
        logger.error("❌ Dhan credentials missing. Skipping WebSocket.")
        return None

    dhan_context = DhanContext(client_id, access_token)

    def on_order_update(order_data: dict):
        """Callback function to process order update data"""
        try:
            # Extract order data from the response
            data = order_data.get('Data', order_data)  # Handle both nested and flat structures
            
            status = data.get('orderStatus')
            order_id = data.get('orderId')
            symbol = data.get('tradingSymbol', 'UNKNOWN')
            
            if not order_id:
                return  # Skip if no order ID
            
            with state_lock:
                # Update Order History
                if 'orders' not in bot_state:
                    bot_state['orders'] = {}
                
                # Track this order
                if order_id not in bot_state['orders']:
                    bot_state['orders'][order_id] = {}
                
                bot_state['orders'][order_id].update(data)
                logger.info(f"⚡ WS Update: {symbol} Order {order_id} → {status}")
                
                # Handle TRADED (Fill)
                if status == "TRADED":
                    qty = data.get('filledQty', data.get('quantity', 0))
                    price = data.get('tradedPrice', data.get('price', 0))
                    logger.info(f"✅ Trade Executed: {symbol} | Qty: {qty} @ ₹{price}")
            
        except Exception as e:
            logger.exception(f"Error processing order update: {e}")

    def run_order_socket():
        """Main WebSocket loop with auto-reconnect"""
        order_ws = OrderUpdate(dhan_context)
        order_ws.on_update = on_order_update

        while True:
            try:
                logger.info("🔄 Connecting to Dhan Order WebSocket...")
                order_ws.connect_to_dhan_websocket_sync()
            except Exception as e:
                logger.error(f"❌ WebSocket Disconnected: {e}. Retrying in 5s...")
                time.sleep(5)

    t = threading.Thread(target=run_order_socket, daemon=True, name="DhanOrderSocket")
    t.start()
    logger.info("✅ Dhan Order WebSocket thread started")
    return t
