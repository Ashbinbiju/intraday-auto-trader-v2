import logging
import threading
import time
import json
from dhanhq import DhanContext, OrderUpdate
from config import config_manager
from state_manager import state_lock

logger = logging.getLogger("DhanOrderSocket")

def _patch_dhan_websocket():
    """
    Monkey-patch dhanhq.OrderSocket to handle concatenated JSON messages.
    Dhan sends multiple JSON objects in one WebSocket message without separators.
    """
    try:
        from dhanhq.orderupdate import OrderSocket
        
        # Save original connect method
        original_connect = OrderSocket.connect_order_update
        
        async def patched_connect(self):
            """Patched version that handles multiple JSON objects"""
            import websockets
            async with websockets.connect(self.order_feed_wss) as websocket:
                auth_message = {
                    "LoginReq": {
                        "MsgCode": 42,
                        "ClientId": str(self.client_id),
                        "Token": str(self.access_token)
                    },
                    "UserType": "SELF"
                }
                
                await websocket.send(json.dumps(auth_message))
                logger.info("✅ Dhan WebSocket authenticated")
                
                async for message in websocket:
                    # Handle multiple concatenated JSON objects
                    try:
                        message_str = message.strip()
                        if not message_str:
                            continue
                        
                        decoder = json.JSONDecoder()
                        idx = 0
                        while idx < len(message_str):
                            try:
                                data, end_idx = decoder.raw_decode(message_str, idx)
                                await self.handle_order_update(data)
                                idx = end_idx
                                # Skip whitespace
                                while idx < len(message_str) and message_str[idx].isspace():
                                    idx += 1
                            except json.JSONDecodeError:
                                if idx < len(message_str):
                                    logger.debug(f"Unparsed data remaining at idx {idx}: {message_str[idx:idx+50]!r}...")
                                break
                    except (TypeError, AttributeError) as e:
                        logger.error(f"JSON parse error: {e}")
        
        # Apply monkey-patch
        OrderSocket.connect_order_update = patched_connect
        logger.info("✅ Dhan WebSocket patch applied")
        return True
    except (ImportError, AttributeError) as e:
        logger.warning(f"⚠️  Could not patch Dhan SDK: {e}")
        return False

def start_dhan_websocket(bot_state):
    """
    Start Dhan Order Update WebSocket.
    Uses official DhanHQ implementation pattern from docs.
    Updates BOT_STATE with real-time order status.
    """
    client_id = config_manager.get("credentials", "dhan_client_id")
    access_token = config_manager.get("credentials", "dhan_access_token")
    
    if not client_id or not access_token:
        logger.error("❌ Credentials Missing. Skipping WebSocket.")
        return

    dhan_context = DhanContext(client_id, access_token)

    def on_order_update(order_data: dict):
        """Callback function to process order update data"""
        try:
            data = order_data.get('Data', {})
            status = data.get('orderStatus')
            order_id = data.get('orderId')
            symbol = data.get('tradingSymbol')
            
            with state_lock:
                # 1. Update Order History
                if 'orders' not in bot_state:
                    bot_state['orders'] = {}
                
                # Check if we are tracking this order
                if order_id in bot_state['orders']:
                    bot_state['orders'][order_id].update(data)
                    logger.info(f"⚡ WS Update: Order {order_id} -> {status}")
                
                # 2. Handle TRADED (Fill)
                if status == "TRADED":
                   logger.info(f"✅ Trade Executed: {symbol} | Qty: {data.get('filledQty')} @ {data.get('tradedPrice')}")
            
        except Exception as e:
            logger.error(f"Error processing order update: {e}")

    def run_order_update():
        """Main order WebSocket loop with auto-reconnect"""
        order_client = OrderUpdate(dhan_context)
        order_client.on_update = on_order_update

        while True:
            try:
                logger.info("🔄 Connecting to Dhan Order WebSocket...")
                order_client.connect_to_dhan_websocket_sync()
            except Exception as e:
                logger.error(f"WebSocket Disconnected: {e}. Retrying in 5s...")
                time.sleep(5)

    t = threading.Thread(target=run_order_update, daemon=True, name="DhanOrderSocket")
    t.start()
    return t
