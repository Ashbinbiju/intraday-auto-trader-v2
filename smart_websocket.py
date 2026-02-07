import threading
import json
import logging
import time
import websocket
import ssl

logger = logging.getLogger("DhanSmartWS")

class OrderUpdateWS:
    def __init__(self, client_id, access_token, bot_state, ws_manager=None):
        self.url = "wss://api-order-update.dhan.co"
        self.client_id = client_id
        self.access_token = access_token
        self.bot_state = bot_state
        self.ws_manager = ws_manager
        self.ws = None
        self.is_running = False
        self.thread = None

    def on_open(self, ws):
        logger.info("✅ Connected to Dhan WebSocket (Threaded)")
        
        # 1. Send Login Request
        masked_token = self.access_token[:4] + "****" + self.access_token[-4:] if self.access_token else "None"
        logger.info(f"📤 Sending Auth Packet for Client: {self.client_id} | Token: {masked_token}")

        auth_packet = {
            "LoginReq": {
                "MsgCode": 42,
                "ClientId": str(self.client_id),
                "Token": str(self.access_token)
            },
            "UserType": "SELF"
        }
        ws.send(json.dumps(auth_packet))

    def on_message(self, ws, message):
        """
        Handles Incoming Messages (Both Text and Binary if library passes them here)
        Note: websocket-client handles pings automatically usually, but Dhan might send custom binary frames.
        """
        try:
            # Handle Binary Heartbeat (0x32) manually if passed as bytes/string
            # Only relevant if 'on_data' is not used.
            if isinstance(message, bytes):
                 if len(message) > 0 and message[0] == 50: # '2'
                    logger.debug("❤️ Heartbeat received. Sending Pong '3'.")
                    ws.send("3")
                    return
                 
            # If message is text '2' (sometimes happen)
            if message == "2":
                 logger.debug("❤️ Heartbeat received (Text). Sending Pong '3'.")
                 ws.send("3")
                 return

            # Parse JSON
            data = json.loads(message)
            self.process_message(data)

        except Exception as e:
            logger.error(f"❌ Error processing message: {e}")

    def on_data(self, ws, message, data_type, continue_flag):
        """
        Explicit handler for frame data (Text vs Binary).
        ABNF.OPCODE_BINARY = 0x2
        ABNF.OPCODE_TEXT = 0x1
        """
        if data_type == websocket.ABNF.OPCODE_BINARY:
            if len(message) > 0 and message[0] == 50: # '2'
                logger.info("❤️ Heartbeat received (Binary '2'). Sending Pong '3'.")
                ws.send("3")
        elif data_type == websocket.ABNF.OPCODE_TEXT:
            # Decode and process
            try:
                decoded = message.decode('utf-8')
                self.on_message(ws, decoded)
            except Exception as e:
                logger.error(f"Text Decode Error: {e}")

    def on_error(self, ws, error):
        logger.error(f"⚠️ WebSocket Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        logger.info(f"🔌 WebSocket Closed: {close_status_code} - {close_msg}")

    def connect(self):
        """
        Starts the WebSocket connection in a separate thread.
        NOTE: This method is now non-blocking (async compatible wrapper not needed here as we use threading)
        """
        self.is_running = True
        
        def run_forever():
            while self.is_running:
                try:
                    # Enable trace for debugging if needed
                    # websocket.enableTrace(True)
                    self.ws = websocket.WebSocketApp(
                        self.url,
                        on_open=self.on_open,
                        on_message=self.on_message,
                        on_error=self.on_error,
                        on_close=self.on_close,
                        on_data=self.on_data # Important for Binary
                    )
                    
                    self.ws.run_forever(
                        sslopt={"cert_reqs": ssl.CERT_NONE},
                        ping_interval=None, # We handle custom pings
                        ping_timeout=10
                    )
                except Exception as e:
                    logger.error(f"WS Run Loop failed: {e}")
                
                if self.is_running:
                    logger.info("Reconnecting in 5s...")
                    time.sleep(5)

        self.thread = threading.Thread(target=run_forever, daemon=True)
        self.thread.start()
        
        # Async compatibility: just return formatted for await
        loop = asyncio.new_event_loop() 
        asyncio.set_event_loop(loop)
        return

    def process_message(self, data):
        msg_type = data.get("Type")
        if msg_type == "order_alert":
            self.handle_order_update(data.get("Data", {}))

    def handle_order_update(self, data):
        order_id = data.get("OrderNo")
        status = data.get("Status")
        symbol = data.get("TradingSymbol") or data.get("DisplayName")
        
        logger.info(f"🔔 Order Update: {symbol} | ID: {order_id} | Status: {status}")

        # Broadcast (Need to be careful with asyncio from thread)
        # For now, just logging. 
        # In real app, put into a queue or use run_coroutine_threadsafe

    def stop(self):
        self.is_running = False
        if self.ws:
            self.ws.close()
