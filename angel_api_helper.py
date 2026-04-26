import logging
import pandas as pd
from datetime import datetime, timedelta
import time
import requests
import json
from SmartApi import SmartConnect
import pyotp
from config import config_manager

logger = logging.getLogger("AngelAPI")

# --- Rate Limiters ---
class RateLimiter:
    def __init__(self, calls_per_second=2):
        self.interval = 1.0 / calls_per_second
        self.last_call = 0
        import threading
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_call
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_call = time.time()

data_limiter = RateLimiter(calls_per_second=2)
quote_limiter = RateLimiter(calls_per_second=1)
order_limiter = RateLimiter(calls_per_second=2)

def get_session():
    try:
        api_key = config_manager.get("credentials", "angel_api_key")
        client_id = config_manager.get("credentials", "angel_client_id")
        pin = config_manager.get("credentials", "angel_pin")
        totp_secret = config_manager.get("credentials", "angel_totp_secret")
        
        if not all([api_key, client_id, pin, totp_secret]):
            logger.error("❌ Angel One credentials missing.")
            return None
            
        obj = SmartConnect(api_key=api_key)
        totp = pyotp.TOTP(totp_secret).now()
        data = obj.generateSession(client_id, pin, totp)
        
        if data['status']:
            logger.info("✅ Angel One Session generated successfully")
            return obj
        else:
            logger.error(f"❌ Angel One Login Failed: {data}")
            return None
    except Exception as e:
        logger.error(f"❌ Angel Session Error: {e}")
        return None

def check_connection(session):
    try:
        if session is None: return False, "NO_SESSION"
        profile = session.getProfile(session.refresh_token)
        if profile and profile.get('status'):
            return True, "OK"
        return False, "TOKEN_EXPIRED"
    except Exception as e:
        return False, f"API_ERROR: {e}"

def load_instrument_map():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        token_map = {}
        for item in data:
            if item['exch_seg'] == 'NSE' and item['instrumenttype'] == '': # Equities
                # Angel Symbol format is "RELIANCE-EQ". We map "RELIANCE" to token.
                symbol = item['symbol'].split('-')[0]
                token_map[symbol] = item['token']
        logger.info(f"✅ Angel One Instrument map loaded. Tokens: {len(token_map)}")
        return token_map
    except Exception as e:
        logger.error(f"❌ Failed to load Angel One tokens: {e}")
        return {}

def fetch_ltp(session, token, symbol):
    quote_limiter.wait()
    try:
        if not token: return None
        
        data = session.ltpData("NSE", symbol + "-EQ", token)
        if data['status']:
            return float(data['data']['ltp'])
    except Exception as e:
        logger.error(f"Error fetching LTP for {symbol}: {e}")
    return None

def fetch_candle_data(session, token, symbol, interval="FIVE_MINUTE", days=10):
    data_limiter.wait()
    try:
        if not token: return None
        
        interval_map = {"ONE_MINUTE": "ONE_MINUTE", "FIVE_MINUTE": "FIVE_MINUTE", "FIFTEEN_MINUTE": "FIFTEEN_MINUTE"}
        angel_interval = interval_map.get(interval, "FIVE_MINUTE")
        
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        
        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": angel_interval,
            "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
            "todate": to_date.strftime("%Y-%m-%d %H:%M")
        }
        response = session.getCandleData(params)
        
        if response['status'] and response['data']:
            df = pd.DataFrame(response['data'], columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)
            return df
            
    except Exception as e:
        logger.error(f"Error fetching candles for {symbol}: {e}")
    return None

def place_order_api(session, params):
    order_limiter.wait()
    try:
        token = params.get('symboltoken')
        symbol = params.get('tradingsymbol')
        params_payload = {
            "variety": "NORMAL",
            "tradingsymbol": symbol + "-EQ" if not symbol.endswith("-EQ") else symbol,
            "symboltoken": str(token),
            "transactiontype": params.get("transactiontype"),
            "exchange": "NSE",
            "ordertype": params.get("ordertype"),
            "producttype": params.get("producttype", "INTRADAY"),
            "duration": "DAY",
            "price": str(params.get("price", 0)),
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(params.get("quantity")),
            "ordertag": params.get("correlation_id")
        }
        response = session.placeOrder(params_payload)
        if response['status']:
            return response['data']['orderid']
        logger.error(f"Order failed: {response}")
    except Exception as e:
        logger.error(f"Place order error: {e}")
    return None

def get_order_status(session, order_id):
    quote_limiter.wait()
    try:
        response = session.orderBook()
        if response['status'] and response['data']:
            for order in response['data']:
                if order['orderid'] == order_id:
                    status = order['status']
                    if status == "complete": return "TRADED"
                    if status == "rejected": return "REJECTED"
                    if status == "cancelled": return "CANCELLED"
                    return "PENDING"
    except Exception as e:
        logger.error(f"Order status error: {e}")
    return "UNKNOWN"

def verify_order_status(session, symbol, correlation_id):
    try:
        response = session.orderBook()
        if response['status'] and response['data']:
            for order in response['data']:
                if order.get('ordertag') == correlation_id:
                    if order['status'] == "complete": return True
    except Exception as e:
        pass
    return False

def fetch_net_positions(session):
    quote_limiter.wait()
    try:
        response = session.position()
        if response['status'] and response['data']:
            positions = []
            for p in response['data']:
                if p['exchange'] == 'NSE' and p['producttype'] == 'INTRADAY':
                    symbol = p['tradingsymbol'].split('-')[0]
                    positions.append({
                        'symbol': symbol,
                        'buyQty': int(p['buyqty']),
                        'sellQty': int(p['sellqty']),
                        'netQty': int(p['netqty']),
                        'realizedProfit': float(p['realised']),
                        'unrealizedProfit': float(p['unrealised'])
                    })
            return positions
    except Exception as e:
        logger.error(f"Net positions error: {e}")
    return None
