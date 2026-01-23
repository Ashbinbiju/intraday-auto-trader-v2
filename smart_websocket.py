import asyncio
import websockets
import json
import logging
import ssl

logger = logging.getLogger("SmartWS")

class OrderUpdateWS:
    def __init__(self, token, bot_state, ws_manager=None):
        self.url = "wss://tns.angelone.in/smart-order-update"
        self.token = token
        self.bot_state = bot_state # Reference to shared state
        self.ws_manager = ws_manager # To broadcast updates
        self.ws = None
        self.is_running = False

    async def connect(self):
        """
        Connects and listens to the WebSocket.
        """
        self.is_running = True
        headers = {
            "Authorization": f"Bearer {self.token}"
        }
        
        # SSL Context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        logger.info(f"Connecting to Order WebSocket...")
        
        while self.is_running:
            try:
                async with websockets.connect(self.url, additional_headers=headers, ssl=ssl_context) as websocket:
                    self.ws = websocket
                    logger.info("Order WebSocket Connected!")
                    
                    # Start Heartbeat Task
                    asyncio.create_task(self._heartbeat())

                    async for message in websocket:
                        await self._process_message(message)

            except Exception as e:
                logger.error(f"Order WS Disconnected: {e}. Retrying in 5s...")
                await asyncio.sleep(5)
    
    async def _heartbeat(self):
        """
        Sends/Expects heartbeat.
        """
        while self.is_running and self.ws:
            try:
                await self.ws.send("ping")
                await asyncio.sleep(10)
            except:
                break

    async def _process_message(self, message):
        """
        Parses incoming order updates.
        """
        try:
            if message == "pong":
                return
            
            data = json.loads(message)
            
            # Initial Response check
            if "status-code" in data and data.get("status-code") != "200":
                logger.error(f"WS Error: {data.get('error-message')}")
                return

            # Order Data
            if "orderData" in data:
                order = data["orderData"]
                status = order.get("orderstatus", "").lower() # complete, rejected, cancelled
                symbol = order.get("tradingsymbol", "").replace("-EQ", "")
                trans_type = order.get("transactiontype")

                logger.info(f"WS Order Update: {symbol} | {trans_type} | {status}")

                # Update Logic
                if status == "complete":
                    # If it's a SELL, it might be an exit
                    if trans_type == "SELL":
                        if symbol in self.bot_state["positions"]:
                             self.bot_state["positions"][symbol]["status"] = "CLOSED"
                             self.bot_state["positions"][symbol]["exit_price"] = float(order.get("averageprice", 0))
                             self.bot_state["positions"][symbol]["exit_reason"] = "WS_UPDATE"
                             logger.info(f"Position Closed via WS for {symbol}")
                    
                    # If it's a BUY, it might be an entry confirming
                    elif trans_type == "BUY":
                         if symbol in self.bot_state["positions"]:
                             self.bot_state["positions"][symbol]["status"] = "OPEN"
                             # Update entry price if needed
                             self.bot_state["positions"][symbol]["entry_price"] = float(order.get("averageprice", 0))
                
                # Broadcast changes
                if self.ws_manager:
                    await self.ws_manager.broadcast(self.bot_state)

        except Exception as e:
            logger.error(f"Error processing WS msg: {e}")

    def stop(self):
        self.is_running = False
