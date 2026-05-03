import logging
import threading
import time
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

logger = logging.getLogger("AngelStreamWS")

# Global memory for fast LTP lookups
LIVE_LTP_DICT = {}

class AngelStreamWS:
    def __init__(self, session):
        self.session = session
        self.ws = None
        self.connected = False
        self.thread = None
        self.active_tokens = set()
        self._lock = threading.RLock()

    def _on_open(self, wsapp):
        logger.info("Angel One Smart Stream WS Connected!")
        with self._lock:
            self.connected = True
        self._resubscribe_all()

    def _on_data(self, wsapp, message):
        try:
            if isinstance(message, dict):
                token = message.get("token")
                price_paise = message.get("last_traded_price")
                if token and price_paise is not None:
                    # Prices are in paise, divide by 100
                    LIVE_LTP_DICT[token] = price_paise / 100.0
        except Exception as e:
            logger.error(f"Error parsing WS data: {e}")

    def _on_error(self, wsapp, error):
        logger.error(f"Angel One WS Error: {error}")

    def _on_close(self, wsapp, close_status_code, close_msg):
        logger.warning(f"Angel One WS Closed: {close_msg}")
        with self._lock:
            self.connected = False

    def connect_async(self):
        auth_token = self.session.access_token
        if auth_token and not auth_token.startswith("Bearer "):
            auth_token = f"Bearer {auth_token}"
        api_key = self.session.api_key
        client_code = self.session.userId
        feed_token = self.session.feed_token
        
        self.ws = SmartWebSocketV2(auth_token, api_key, client_code, feed_token)
        
        # Monkey patch SmartWebSocketV2 bug where _on_close doesn't accept status args
        def patched_on_close(wsapp, close_status_code=None, close_msg=None):
            if hasattr(self.ws, 'on_close') and self.ws.on_close:
                try:
                    self.ws.on_close(wsapp, close_status_code, close_msg)
                except TypeError:
                    self.ws.on_close(wsapp)
                    
        self.ws._on_close = patched_on_close
        self.ws.on_open = self._on_open
        self.ws.on_data = self._on_data
        self.ws.on_error = self._on_error
        self.ws.on_close = self._on_close
        
        def run_forever():
            from utils import is_market_open
            logger.info("🚀 Starting Angel Smart Stream WS...")
            backoff = 5
            max_backoff = 30
            
            while True:
                market_open, reason = is_market_open()
                if not market_open:
                    with self._lock:
                        if self.connected:
                            logger.info(f"📴 Market closed ({reason}). Stream WS will reconnect when market opens.")
                            self.connected = False
                            try:
                                self.ws.close_connection()
                            except Exception:
                                pass
                    time.sleep(60)
                    continue
                
                try:
                    self.ws.connect()
                    backoff = 5  # Reset backoff only after successful connection cycle
                except Exception as e:
                    logger.error(f"⚠️ Angel Stream WS Connection Error: {e}")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                    
        self.thread = threading.Thread(target=run_forever, daemon=True)
        self.thread.start()

    def _resubscribe_all(self):
        with self._lock:
            if not self.active_tokens:
                return
            tokens_to_sub = list(self.active_tokens)
        self.subscribe(tokens_to_sub)

    def subscribe(self, tokens: list):
        if not tokens:
            return
        
        with self._lock:
            new_tokens = set(tokens) - self.active_tokens
            if not new_tokens:
                return # Already subscribed to all of them
                
            self.active_tokens.update(new_tokens)
            is_connected = self.connected
            total_active = len(self.active_tokens)
        
        if is_connected and self.ws:
            token_list = [{"exchangeType": 1, "tokens": list(new_tokens)}]
            correlation_id = f"sub_{int(time.time())}"
            # mode: 1 is LTP
            try:
                self.ws.subscribe(correlation_id, 1, token_list)
                logger.info(f"WS Subscribed to {len(new_tokens)} new tokens. Total active: {total_active}")
            except Exception as e:
                logger.error(f"Failed to subscribe to tokens: {e}")

    def unsubscribe(self, tokens: list):
        if not tokens:
            return
            
        with self._lock:
            unsub_tokens = set(tokens).intersection(self.active_tokens)
            if not unsub_tokens:
                return
            
            for t in unsub_tokens:
                self.active_tokens.discard(t)
            is_connected = self.connected
            
        if is_connected and self.ws:
            token_list = [{"exchangeType": 1, "tokens": list(unsub_tokens)}]
            correlation_id = f"unsub_{int(time.time())}"
            try:
                self.ws.unsubscribe(correlation_id, 1, token_list)
                logger.info(f"WS Unsubscribed from {len(unsub_tokens)} tokens.")
            except Exception as e:
                logger.error(f"Failed to unsubscribe from tokens: {e}")

