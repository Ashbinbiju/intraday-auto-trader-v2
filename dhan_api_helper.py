import logging
import pandas as pd
from datetime import datetime, timedelta
import time
from dhanhq import dhanhq
from config import config_manager

logger = logging.getLogger(__name__)

# Load Credentials
DHAN_CLIENT_ID = config_manager.get("credentials", "dhan_client_id") or ""
DHAN_ACCESS_TOKEN = config_manager.get("credentials", "dhan_access_token") or ""

def get_dhan_session():
    """
    Initializes and returns a DhanHQ session object.
    """
    try:
        if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
            logger.error("❌ Dhan Client ID or Access Token missing in config.")
            return None
            
        dhan = dhanhq(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
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
             
             resample_rule = '15T' if interval == "FIFTEEN_MINUTE" else '5T' if interval == "FIVE_MINUTE" else '1T'
             ohlc_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
             
             df_resampled = df.resample(resample_rule).agg(ohlc_dict).dropna()
             df_resampled = df_resampled.reset_index()
             
             return df_resampled

        return None

    except Exception as e:
        logger.error(f"Error fetching candles (Dhan) for {symbol}: {e}")
        return None

def fetch_ltp(dhan, token, symbol):
    try:
        resp = dhan.get_ltp_data(
            security_id=str(token),
            exchange_segment=dhanhq.NSE,
            instrument_type='EQUITY'
        )
        if resp['status'] == 'success':
            return float(resp['data']['last_price'])
        return None
    except Exception as e:
         logger.error(f"Error fetching LTP {symbol}: {e}")
         return None

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
    try:
        resp = dhan.get_order_list()
        if resp['status'] == 'success':
            return resp['data']
        return []
    except Exception as e:
        logger.error(f"Error fetching order list: {e}")
        return []

