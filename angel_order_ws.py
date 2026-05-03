import logging
import threading
import time
import json
import copy
from datetime import datetime
from SmartApi.smartWebSocketOrderUpdate import SmartWebSocketOrderUpdate
from state_manager import save_state, state_lock
from database import log_trade_execution
from config import config_manager
import asyncio

logger = logging.getLogger("AngelOrderWS")

class AngelOrderWS:
    def __init__(self, session, bot_state, ws_manager=None):
        self.session = session
        self.bot_state = bot_state
        self.ws_manager = ws_manager
        self.ws = None
        self.thread = None
        self.connected = False

    def _on_open(self, wsapp):
        logger.info("Angel One Order Update WS Connected! (AB00)")
        self.connected = True

    def _on_data(self, wsapp, message):
        try:
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = message
                
            order_status = data.get("order-status")
            if order_status == "AB00":
                logger.info("Order Update WS: Connection Successful")
                return
                
            order_data = data.get("orderData")
            if not order_data:
                return
                
            status = order_data.get("status", "").lower()
            ordertag = order_data.get("ordertag", "")
            symbol = order_data.get("tradingsymbol", "").replace("-EQ", "")
            orderid = order_data.get("orderid", "")
            text = order_data.get("text", "")
            
            logger.info(f"Order WS Event: {symbol} | Status: {status} | Tag: {ordertag} | ID: {orderid} | {text}")
            
            if status in ["complete", "rejected", "cancelled"]:
                self._handle_execution(symbol, ordertag, status, order_data)
                
        except Exception as e:
            logger.error(f"Error parsing Order WS data: {e}")

    def _handle_execution(self, symbol, ordertag, status, order_data):
        state_snapshot = None
        pos_copy = None
        should_dispatch = False
        avg_price = 0.0

        with state_lock:
            pos = self.bot_state["positions"].get(symbol)
            if not pos:
                return
                
            # If position is OPEN and we sent an exit order
            if pos["status"] == "OPEN" and pos.get("exit_in_progress"):
                if status == "complete":
                    pos["status"] = "CLOSED"
                    try:
                        avg_price = float(order_data.get("averageprice") or 0)
                        if avg_price <= 0:
                            avg_price = float(order_data.get("price") or 0)
                    except (ValueError, TypeError):
                        avg_price = 0.0
                        logger.warning(f"Could not parse price for {symbol}, defaulting to 0")
                    
                    pos["exit_price"] = avg_price
                    # exit_reason is usually set by main.py, but fallback if missing
                    pos.setdefault("exit_reason", "WS_CONFIRMED")
                    pos['exit_time'] = datetime.now().isoformat()
                    
                    logger.info(f"✅ WS Confirmed Exit for {symbol} at {pos['exit_price']}")
                    
                    # Deep copy pos and bot_state snapshot for I/O outside lock
                    pos_copy = copy.deepcopy(pos)
                    state_snapshot = copy.deepcopy(self.bot_state)
                    should_dispatch = True
                    
                elif status in ["rejected", "cancelled"]:
                    pos["exit_in_progress"] = False # Unlock so polling/scanner can try again
                    logger.warning(f"⚠️ WS Confirmed Exit Rejected/Cancelled for {symbol}")
                    state_snapshot = copy.deepcopy(self.bot_state)

        # Perform I/O outside the lock
        if state_snapshot is not None:
            save_state(state_snapshot)
            
        # Dispatch logging and broadcast asynchronously
        if should_dispatch and self.ws_manager:
            threading.Thread(target=self._dispatch_io, args=(pos_copy, avg_price), daemon=True).start()

    def _dispatch_io(self, pos_copy, avg_price):
        try:
            leverage = config_manager.get("position_sizing", "leverage_equity") or 1.0
            log_trade_execution(pos_copy, avg_price, pos_copy['exit_reason'], leverage)
            
            # Broadcast to UI
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.ws_manager.broadcast(self.bot_state))
            loop.close()
        except Exception as e:
            logger.error(f"Error in WS async I/O dispatch: {e}")

    def _on_error(self, wsapp, error):
        logger.error(f"Angel Order WS Error: {error}")

    def _on_close(self, wsapp, close_status_code, close_msg):
        logger.warning(f"Angel Order WS Closed: {close_msg}")
        self.connected = False

    async def connect_async(self):
        auth_token = self.session.access_token
        if auth_token and not auth_token.startswith("Bearer "):
            auth_token = f"Bearer {auth_token}"
        api_key = self.session.api_key
        client_code = self.session.userId
        feed_token = self.session.feed_token
        
        self.ws = SmartWebSocketOrderUpdate(auth_token, api_key, client_code, feed_token)
        self.ws.on_open = self._on_open
        self.ws.on_data = self._on_data
        self.ws.on_error = self._on_error
        self.ws.on_close = self._on_close
        
        def run_forever():
            from utils import is_market_open
            logger.info("🚀 Starting Angel Order Update WS...")
            backoff = 5  # Initial retry delay (seconds)
            max_backoff = 30
            
            while True:
                # Don't attempt connection when market is closed
                market_open, reason = is_market_open()
                if not market_open:
                    if self.connected:
                        logger.info(f"📴 Market closed ({reason}). Order WS will reconnect when market opens.")
                        self.connected = False
                    time.sleep(60)  # Check every 60s instead of hammering every 5s
                    continue
                
                try:
                    backoff = 5  # Reset backoff on new connection attempt during market hours
                    self.ws.connect()
                except Exception as e:
                    logger.error(f"⚠️ Angel Order WS Connection Error: {e}")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)  # Exponential backoff: 5 → 10 → 20 → 30s
                    
        self.thread = threading.Thread(target=run_forever, daemon=True)
        self.thread.start()
