from state_manager import state_lock

logger = logging.getLogger("DhanOrderSocket")

def start_dhan_websocket(bot_state):
    """
    Start Dhan Order Update WebSocket.
    Updates BOT_STATE with real-time order status.
    """
    client_id = config_manager.get("credentials", "dhan_client_id")
    access_token = config_manager.get("credentials", "dhan_access_token")
    
    if not client_id or not access_token:
        logger.error("❌ Credentials Missing. Skipping WebSocket.")
        return

    dhan_context = DhanContext(client_id, access_token)

    async def on_connect():
        logger.info("✅ Connected to Dhan Order WebSocket")

    async def on_message(instance, message):
        # logger.info(f"Received: {message}")
        pass

    def on_order_update(order_data):
        try:
            status = order_data.get('orderStatus')
            order_id = order_data.get('orderId')
            symbol = order_data.get('tradingSymbol')
            
            with state_lock:
                # 1. Update Order History
                if 'orders' not in bot_state: bot_state['orders'] = {}
                
                # Check if we are tracking this order
                if order_id in bot_state['orders']:
                    bot_state['orders'][order_id].update(order_data)
                    logger.info(f"⚡ WS Update: Order {order_id} -> {status}")
                
                # 2. Handle TRADED (Fill)
                if status == "TRADED":
                   logger.info(f"✅ Trade Executed: {symbol} | Qty: {order_data.get('filledQty')} @ {order_data.get('tradedPrice')}")
                   # Logic to update Position Status can be added here
                   # But main loop 'manage_positions' handles P&L updates robustly.
                   # Use this mainly for instant feedback.
            
        except Exception as e:
            logger.error(f"WS Error: {e}")

    def run_socket():
        while True:
            try:
                # Initialize OrderUpdate Class
                order_client = OrderUpdate(dhan_context)
                
                # Assign Callback (Note: DhanHQ uses 'on_update' as property setter sometimes? 
                # Checking source: It seems SDK calls 'self.on_update(data)'?
                # Actually, SDK doc says: order_client = OrderUpdate(dhan_context); order_client.connect_to_dhan_websocket_sync()
                # But how do we pass callback?
                # User snippet: `order_client = OrderUpdate(...)` (Wait, snippet didn't assign callback? 
                # Ah! User snippet: `order_client.on_update = on_order_update`)
                
                # Using user provided pattern:
                # order_client = OrderUpdate(dhan_context)
                # order_client.on_update = on_order_update (Wait, OrderUpdate doesn't seem to expose this in older versions?
                # But for 2.2.0rc1 it might)
                
                # Let's trust user snippet pattern
                # If library structure differs, we might need to subclass or inspect.
                # Assuming simple property assignment works as per snippet. 
                
                # BUT wait, the user said:
                # `order_client = OrderUpdate(dhan_context)`
                # `order_client.on_update = on_order_update` (Is this valid?)
                # Wait, the snippet had `order_client = OrderUpdate(dhan_context)` then `order_client.connect...`
                # Where is set callback?
                # AH! Snippet line 21: `order_client.on_update = on_order_update` 
                # Okay, using property assignment.
                
                logger.info("Connecting to Dhan Order WebSocket...")
                # Note: creating fresh instance every loop in case of disconnect
                order_ws = OrderUpdate(dhan_context)
                
                # Monkey-patch or assign callback
                # Alternatively, pass it in constructor if supported
                # Snippet suggests property.
                order_ws.on_update = on_order_update 
                
                order_ws.connect_to_dhan_websocket_sync()
                
            except Exception as e:
                logger.error(f"WS Disconnected: {e}. Retrying in 5s...")
                time.sleep(5)

    t = threading.Thread(target=run_socket, daemon=True, name="DhanOrderSocket")
    t.start()
    return t
