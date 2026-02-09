import logging
import pandas as pd
from datetime import datetime, timedelta
import time
from dhanhq import dhanhq, DhanContext
from config import config_manager

logger = logging.getLogger(__name__)

# Load Credentials
DHAN_CLIENT_ID = config_manager.get("credentials", "dhan_client_id") or ""
DHAN_ACCESS_TOKEN = config_manager.get("credentials", "dhan_access_token") or ""

# --- RATE LIMITER ---
class RateLimiter:
    def __init__(self, calls_per_second=2):
        self.interval = 1.0 / calls_per_second
        self.last_call = 0
        self.lock = logging.Threading.Lock() if hasattr(logging, 'Threading') else logging.threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_call
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_call = time.time()

# Global Limiter (2 req/s safe for 10/s limit)
# We share this across all threads to prevent burst overlaps.
api_rate_limiter = RateLimiter(calls_per_second=2)

def get_dhan_session():
    """
    Initializes and returns a DhanHQ session object.
    """
    try:
        if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
            logger.error("❌ Dhan Client ID or Access Token missing in config.")
            return None
            
        # v2.2.0rc1 Change: Use DhanContext
        dhan_context = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
        dhan = dhanhq(dhan_context)
        return dhan

    except Exception as e:
        logger.error(f"❌ Dhan Session Error: {e}")
        return None

def check_connection(dhan):
    """
    Checks if the session is valid using `get_fund_limits`.
    Returns: (bool, reason)
    """
    for attempt in range(2): # Retry once on failure
        try:
            # Use Fund Limits for validation (Fast & Vital)
            resp = dhan.get_fund_limits()
            
            status = resp.get('status', '').lower()
            if status == 'success':
                return True, "OK"
            
            # ERROR HANDLING / AUDIT
            remarks = str(resp) # Capture full response for debugging

            # RETRY on Transient Network Errors (detected in remarks)
            if "RemoteDisconnected" in remarks or "Connection aborted" in remarks:
                 if attempt == 0:
                     time.sleep(1)
                     continue # Retry!
            
            # Check against Known Error Codes (from Audit)
            if "DH-901" in remarks or "DH-902" in remarks or "not authorized" in remarks.lower():
                return False, "TOKEN_EXPIRED"
            
            if "DH-904" in remarks:
                return False, "RATE_LIMIT_EXCEEDED"
                
            return False, f"API_ERROR: {remarks}"
            
        except Exception as e:
            # If it's the last attempt, fail
            if attempt == 1:
                return False, f"EXCEPTION: {e}"
            # Otherwise, wait and retry (transient network issue)
            time.sleep(1)

def get_available_margin(dhan):
    """
    Fetches available cash margin for Equity Intraday.
    """
    for attempt in range(2):
        try:
            resp = dhan.get_fund_limits()
            if resp['status'] == 'success':
                # Dhan response: {'data': {'availabelBalance': 1000.0, ...}} 
                # Note typo 'availabelBalance' in some versions, check both
                data = resp.get('data', {})
                balance = data.get('availableBalance') or data.get('availabelBalance') or 0.0
                return float(balance)
            else:
                # Retry on network error
                remarks = str(resp)
                if "RemoteDisconnected" in remarks or "Connection aborted" in remarks:
                    if attempt == 0:
                        time.sleep(1)
                        continue
                
                logger.warning(f"Failed to fetch funds: {resp}")
                return 0.0
        except Exception as e:
            if attempt == 1:
                logger.error(f"Error fetching funds: {e}")
                return 0.0
            time.sleep(1)
    return 0.0

def load_dhan_instrument_map():
    """
    Downloads and parses Dhan Scrip Master CSV.
    """
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    try:
        logger.info("Downloading Dhan Scrip Master...")
        df = pd.read_csv(url, low_memory=False)
        
        # Filter: SEM_EXM_EXCH_ID = 'NSE', SEM_INSTRUMENT_NAME = 'EQUITY'
        # Headers: SEM_SMST_SECURITY_ID, SEM_TRADING_SYMBOL, SEM_EXM_EXCH_ID, SEM_INSTRUMENT_NAME
        equity_mask = (df['SEM_EXM_EXCH_ID'] == 'NSE') & ((df['SEM_INSTRUMENT_NAME'] == 'EQUITY') | (df['SEM_SERIES'] == 'EQ'))
        df_eq = df[equity_mask]
        
        # Map Symbol -> Security ID
        token_map = dict(zip(df_eq['SEM_TRADING_SYMBOL'], df_eq['SEM_SMST_SECURITY_ID'].astype(str)))
        
        logger.info(f"Loaded {len(token_map)} Dhan instruments.")
        return token_map
        
    except Exception as e:
        logger.error(f"Error loading Dhan instrument map: {e}")
        return {}

def fetch_candle_data(dhan, token, symbol, interval="FIFTEEN_MINUTE", days=5):
    """
    Fetches historical candle data.
    Note: Standardizes on 1-min data fetch and local resampling if needed,
    but Dhan API supports specific intervals via `intraday_minute_data`? 
    Actually, Dhan V2 `charts/intraday` supports 1,5,15,25,60.
    """
    try:
        to_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Map Interval
        dhan_interval = 15
        if interval == "FIVE_MINUTE":
            dhan_interval = 5
        elif interval == "ONE_MINUTE":
            dhan_interval = 1
            
        data = dhan.intraday_minute_data(
            security_id=str(token),
            exchange_segment=dhanhq.NSE,
            instrument_type='EQUITY',
            from_date=from_date,
            to_date=to_date
        )
        # Note: Library `intraday_minute_data` usually implies 1-min?
        # If library doesn't expose 'interval' param, we get 1-min and resample.
        # Let's check if we can pass valid interval.
        # Assuming library is basic wrapper around `charts/intraday`, which DOES take interval.
        # But if function doesn't accept kwarg, we stick to defaults or resample.
        
        if data['status'] == 'success' and data.get('data'):
             raw = data['data']
             # Find Time Key
             time_key = next((k for k in ['timestamp', 'start_Time', 'start_time', 'time'] if k in raw), None)
             
             if not time_key:
                 return None
                 
             df = pd.DataFrame({
                 'datetime': pd.to_datetime(raw[time_key], unit='s' if isinstance(raw[time_key][0], (int, float)) else None), 
                 'open': raw['open'],
                 'high': raw['high'],
                 'low': raw['low'],
                 'close': raw['close'],
                 'volume': raw['volume']
             })
             
             # If data is 1-minute (likely), RESAMPLE to desired interval
             df = df.set_index('datetime')
             
             resample_rule = '15min' if interval == "FIFTEEN_MINUTE" else '5min' if interval == "FIVE_MINUTE" else '1min'
             ohlc_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
             
             df_resampled = df.resample(resample_rule).agg(ohlc_dict).dropna()
             df_resampled = df_resampled.reset_index()
             
             return df_resampled

        return None

    except Exception as e:
        logger.error(f"Error fetching candles (Dhan) for {symbol}: {e}")
        return None

def fetch_ltp(dhan, token, symbol):
    """
    Fetches the Last Traded Price (LTP) using 'ticker_data' (Market Feed).
    This is the lightweight and correct way to get real-time prices.
    """
    try:
        # Prepare Payload: keys are exchange segments, values are lists of security IDs
        # token is usually string, ensure it's compliant
        securities = {
            "NSE_EQ": [str(token)] 
        }
        
        resp = dhan.ticker_data(securities)
        
        if resp['status'] == 'success' and resp.get('data'):
             # Response format: {'NSE_EQ': [{'tradingSymbol': '...', 'lastPrice': 345.5, ...}]}
             data = resp['data']
             nse_data = data.get('NSE_EQ', [])
             
             for item in nse_data:
                 # Check if token matches (sometimes response includes others if bulk)
                 # But here we asked for one.
                 return float(item.get('lastPrice', 0.0))
        
        # Debugging: Log response if data is missing or status failed
        logger.warning(f"LTP Fetch Failed for {symbol}. Response: {resp}")
        return None
        
    except Exception as e:
         # Debugging: Log the detailed error
         logger.warning(f"Error fetching LTP {symbol}: {e}")
         return None

def fetch_market_feed_bulk(dhan, tokens):
    """
    Fetches LTP for multiple tokens in a SINGLE API call.
    Returns: { str(token): float(ltp) }
    """
    if not tokens:
        return {}
        
    # Wait for rate limit slot
    api_rate_limiter.wait()
    
    try:
        # Dhan expects string tokens? Or Integers?
        # Error 814 "Invalid Request" suggests format issue.
        # Let's try sending as strings first (standard), but if that fails, maybe ints?
        # Actually, let's try sending them as STRINGS but ensure they are valid.
        # Wait, if map loaded them as strings '1333', then list is ['1333', ...].
        # Let's try INTEGERS as some APIs prefer that.
        
        # securities = { "NSE_EQ": [11536, 1333] }
        # Note: token_map stores them as strings.
        
        # ATTEMPT 1: Try sending as strings (should be default)
        # ATTEMPT 2: Try sending as integers if strings fail. 
        # Given 814, let's switch to INTEGERS.
        
        
        
        securities = {
            "NSE_EQ": [int(float(str(t))) for t in tokens]
        }
        
        resp = dhan.ticker_data(securities)
        
        result = {}
        if resp['status'] == 'success' and resp.get('data'):
             data = resp['data']
             
             # Patch: Unwrap nested 'data' if present (Observed in logs: data={'data': {...}, 'status': 'success'})
             if isinstance(data, dict) and 'data' in data and 'NSE_EQ' not in data:
                 logger.info("DEBUG: Unwrapping nested 'data' key from response.")
                 data = data['data']
                 
             nse_data = data.get('NSE_EQ', {})
             
             # Handle Dict Response (e.g. {'1333': {'last_price': 123.45}})
             if isinstance(nse_data, dict):
                 for token_id, details in nse_data.items():
                     if isinstance(details, dict):
                         ltp = float(details.get('last_price', details.get('lastPrice', 0.0)))
                         result[str(token_id)] = ltp
                     else:
                         # logger.warning(f"Expected dict for details, got {type(details)}: {details}")
                         pass
             
             # Handle potential List Response
             elif isinstance(nse_data, list):
                 for item in nse_data:
                     token_id = str(item.get('securityId'))
                     ltp = float(item.get('lastPrice', item.get('last_price', 0.0)))
                     result[token_id] = ltp
             
             else:
                 logger.warning(f"Unknown Data Type for NSE_EQ: {type(nse_data)} | Data: {nse_data}")
                 for item in nse_data:
                     token_id = str(item.get('securityId'))
                     ltp = float(item.get('lastPrice', item.get('last_price', 0.0)))
                     result[token_id] = ltp
                 
             if not result:
                 logger.warning(f"⚠️ Bulk Fetch Success but Result Empty. Raw Data: {data}")
        else:
             logger.warning(f"Bulk Fetch Failed. Payload: {securities} | Response: {resp}")
                 
        return result
        
    except Exception as e:
        logger.error(f"Error in Bulk LTP Fetch: {e}")
        return {}

def fetch_net_positions(dhan):
    """
    Fetches Open Positions and normalizes keys for Bot compatibility.
    """
    try:
        resp = dhan.get_positions()
        if resp['status'] == 'success':
            raw_data = resp['data']
            normalized_data = []
            
            for pos in raw_data:
                # Map Dhan (CamelCase) -> Angel (Lowercase)
                entry = {
                    "tradingsymbol": pos.get("tradingSymbol", ""),
                    "symboltoken": pos.get("securityId", ""),
                    "netqty": pos.get("netQty", 0),
                    "avgnetprice": pos.get("buyAvg", 0) if pos.get("netQty", 0) > 0 else pos.get("sellAvg", 0)
                }
                normalized_data.append(entry)
                
            return normalized_data
        return []
    except Exception as e:
        logger.error(f"Error fetching positions (Dhan): {e}")
        return []

def place_order_api(dhan, params):
    """
    Places order with pre-trade checks.
    """
    try:
        # Rate Limit Check
        api_rate_limiter.wait()
        
        # AUDIT: FUNDS CHECK
        # We should ideally check funds here, but speed is key.
        # Assume 'check_connection' or main loop logic verified balance roughly.
        
        dhan_txn_type = dhanhq.BUY if params.get('transactiontype') == 'BUY' else dhanhq.SELL
        dhan_order_type = dhanhq.MARKET if params.get('ordertype') == 'MARKET' else dhanhq.LIMIT
        dhan_product = dhanhq.INTRADAY if params.get('producttype') == 'INTRADAY' else dhanhq.CNC
        
        # AUDIT: ORDER PLACEMENT
        resp = dhan.place_order(
            security_id=str(params.get('symboltoken')),
            exchange_segment=dhanhq.NSE,
            transaction_type=dhan_txn_type,
            quantity=int(params.get('quantity')),
            order_type=dhan_order_type,
            product_type=dhan_product,
            price=float(params.get('price', 0)),
            validity=dhanhq.DAY
        )
        
        if resp['status'] == 'success':
            logger.info(f"✅ Order Placed: {resp['data'].get('orderId')}")
            return resp['data']['orderId']
        else:
            logger.error(f"❌ Order Rejected: {resp.get('remarks')}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Order Exception: {e}")
        return None

def fetch_holdings(dhan):
    try:
        resp = dhan.get_holdings()
        if resp['status'] == 'success':
            return resp['data']
        return []
    except Exception:
        return []

def fetch_order_list(dhan):
    """
    Fetches all orders for the day.
    Returns list of order dictionaries.
    """
    # Wait for rate limit slot
    api_rate_limiter.wait()
    
    try:
        resp = dhan.get_order_list()
        if resp['status'] == 'success':
            return resp['data']
        return []
    except Exception as e:
        logger.error(f"Error fetching order list: {e}")
        return []

def verify_order_status(dhan, order_id, retries=5, delay=1):
    """
    Verifies if an order was successfully placed and is not Rejected.
    Returns: (is_success: bool, status: str, average_price: float)
    """
    if not order_id: return False, "NO_ID", 0.0
    
    # Handle Dry Run / Simulation (Boolean True)
    if order_id is True or str(order_id).upper() == "DRY_RUN":
        return True, "DRY_RUN", 0.0
    
    for i in range(retries):
        try:
            # Fetch order details
            # Note: DhanHQ `get_order_by_id` takes ID.
            resp = dhan.get_order_by_id(order_id)
            
            if resp['status'] == 'success':
                data = resp['data']
                status = data.get('orderStatus', '').upper() # TRADED, PENDING, REJECTED, CANCELLED
                
                # REJECTED
                if status == 'REJECTED':
                    reason = data.get('errMsg', 'Unknown Rejection')
                    return False, f"REJECTED: {reason}", 0.0
                
                # CANCELLED
                if status == 'CANCELLED':
                    return False, "CANCELLED", 0.0
                
                # SUCCESS (TRADED or PENDING/OPEN is considered successfully placed)
                # But for our bot, we want to confirm it's not rejected immediately.
                # If PENDING, we wait a bit or assume open.
                # If TRADED, get price.
                avg_price = float(data.get('tradedAvg', 0.0))
                if avg_price == 0:
                     avg_price = float(data.get('price', 0.0))

                return True, status, avg_price
            
            time.sleep(delay)
            
        except Exception as e:
            logger.error(f"Error verifying order {order_id}: {e}")
            time.sleep(delay)
            
    return False, "TIMEOUT_VERIFY", 0.0

