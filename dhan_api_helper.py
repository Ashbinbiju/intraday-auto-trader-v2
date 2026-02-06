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
        # Validate connection by fetching holdings (lightweight call)
        # Note: 'get_holdings' is standard method in dhanhq
        test_resp = dhan.get_holdings()
        
        if test_resp['status'] == 'success':
            logger.info("✅ Dhan API Connected Successfully.")
            return dhan
        elif test_resp.get('remarks', {}).get('error_code') == 'RS-9005':
            logger.info("✅ Dhan API Connected (No Holdings Found).")
            return dhan
        else:
            logger.error(f"❌ Dhan Connection Failed: {test_resp.get('remarks', 'Unknown Error')}")
            return None

    except Exception as e:
        logger.error(f"❌ Dhan Session Error: {e}")
        return None

def load_dhan_instrument_map():
    """
    Downloads and parses Dhan Scrip Master CSV to map Symbol -> Security ID.
    returns: dict {'INFY': '12345', ...}
    """
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    try:
        logger.info("Downloading Dhan Scrip Master...")
        df = pd.read_csv(url)
        
        # Filter: SEM_EXM_EXCH_ID = 'NSE', SEM_INSTRUMENT_NAME = 'EQUITY'
        # Columns might vary, usually: SEM_SMST_SECURITY_ID, SEM_TRADING_SYMBOL, SEM_EXM_EXCH_ID, SEM_INSTRUMENT_NAME
        
        # Check columns (Dhan csv headers can trigger key errors if guessed wrong)
        # Expected: SEM_SMST_SECURITY_ID, SEM_TRADING_SYMBOL, SEM_EXM_EXCH_ID, SEM_INSTRUMENT_NAME
        
        # Optimization: fast filtering
        equity_mask = (df['SEM_EXM_EXCH_ID'] == 'NSE') & ((df['SEM_INSTRUMENT_NAME'] == 'EQUITY') | (df['SEM_SERIES'] == 'EQ'))
        df_eq = df[equity_mask]
        
        token_map = dict(zip(df_eq['SEM_TRADING_SYMBOL'], df_eq['SEM_SMST_SECURITY_ID'].astype(str)))
        
        logger.info(f"Loaded {len(token_map)} Dhan instruments.")
        return token_map
        
    except Exception as e:
        logger.error(f"Error loading Dhan instrument map: {e}")
        return {}

def fetch_candle_data(dhan, token, symbol, interval="FIFTEEN_MINUTE", days=5, retries=3, delay=1):
    """
    Fetches historical candle data from Dhan.
    
    Args:
        dhan: DhanHQ session object
        token: Security ID (Dhan uses different IDs than Angel, need to handle this!)
        symbol: Symbol Name
        interval: "FIFTEEN_MINUTE" | "FIVE_MINUTE" (Needs mapping to Dhan codes)
        days: Number of days back
        
    Returns:
        pd.DataFrame or None
    """
    # Map Interval to Dhan Codes
    # Dhan Interval Codes: 1: 1min, 5: 5min, 15: 15min, 25: 60min, 'D': Daily
    interval_map = {
        "ONE_MINUTE": dhanhq.IntradayMinute,
        "FIVE_MINUTE": dhanhq.IntradayFiveMinutes,
        "FIFTEEN_MINUTE": dhanhq.IntradayFifteenMinutes,
        "ONE_HOUR": dhanhq.IntradaySixtyMinutes,
        "ONE_DAY": dhanhq.Daily
    }
    
    # Defaults and Error Handling for invalid interval
    dhan_interval = interval_map.get(interval, dhanhq.IntradayFifteenMinutes)

    try:
        # Calculate Date Range
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Dhan 'get_intraday_data' expects: security_id, exchange_segment, instrument_type
        # We need to ensure 'token' passed here is actually the Dhan Security ID.
        # IF token is from AngelOne map, THIS WILL FAIL. 
        # TODO: WE NEED A DHAN INSTRUMENT MAP.
        
        # For now, assuming 'token' IS the Dhan Security ID (caller must provide correct ID).
        # We might need to swap the token_map logic in main.py too.
        
        # Security ID must be int or string depending on lib? Usually string.
        # Exchange Segment: NSE_EQ (Equity), NSE_FNO (Derivatives)
        # We primarily trade NSE Equity in this bot.
        
        data = dhan.intraday_minute_data(
            security_id=str(token),
            exchange_segment=dhanhq.NSE,
            instrument_type='EQUITY',
            from_date=from_date,
            to_date=to_date
        )
        
        if data['status'] == 'success' and data.get('data'):
             # Dhan returns data in: start_time, open, high, low, close, volume (list of lists or dict)
             # Actually 'data' key usually has 'stat' and 'data' is the list.
             # Need to verify response structure. Assuming standard dict for now.
             
             # Response Structure (typical): {'status': 'success', 'data': {'start_time': [...], 'open': [...], ...}}
             raw = data['data']
             
             if not raw.get('start_Time'):
                 return None
                 
             df = pd.DataFrame({
                 'datetime': pd.to_datetime(raw['start_Time']), # Dhan usually gives 'start_Time'
                 'open': raw['open'],
                 'high': raw['high'],
                 'low': raw['low'],
                 'close': raw['close'],
                 'volume': raw['volume']
             })
             
             # Filter based on requested interval? 
             # Wait, `intraday_minute_data` gives 1-min data. 
             # Users usually want aggregated candles if requesting 15 min.
             # Dhan has `historical_daily_data` but for intraday custom timeframe?
             # Docs say `intraday_minute_data` provides 1 min data.
             # We might need to Resample 1-min data to 5/15 min if Dhan doesn't support direct interval fetch for historical.
             # UPDATED: Dhan lib mentions `intraday_minute_data`.
             
             # RESAMPLING LOGIC if interval != 1min
             df = df.set_index('datetime')
             
             resample_rule = '15T' if interval == "FIFTEEN_MINUTE" else '5T' if interval == "FIVE_MINUTE" else '1T'
             
             ohlc_dict = {
                 'open': 'first',
                 'high': 'max',
                 'low': 'min',
                 'close': 'last',
                 'volume': 'sum'
             }
             
             df_resampled = df.resample(resample_rule).agg(ohlc_dict).dropna()
             df_resampled = df_resampled.reset_index()
             
             return df_resampled

        else:
            logger.warning(f"⚠️ Dhan Fetch Failed {symbol}: {data.get('remarks')}")
            return None

    except Exception as e:
        logger.error(f"Error fetching candles (Dhan) for {symbol}: {e}")
        return None

def fetch_ltp(dhan, token, symbol):
    """
    Fetches LTP from Dhan.
    """
    try:
        # Dhan get_positions or get_marketfeed?
        # get_latest_price might be available in some versions, else use packet.
        # Simpler: Use `get_ltp_data` or `getting quotes`.
        # SDK has `quote`.
        
        resp = dhan.get_ltp_data(
            security_id=str(token),
            exchange_segment=dhanhq.NSE,
            instrument_type='EQUITY'
        )
        
        if resp['status'] == 'success':
            return float(resp['data']['last_price'])
        return None
        
    except Exception as e:
         logger.error(f"Error fetching LTP (Dhan) {symbol}: {e}")
         return None

def fetch_net_positions(dhan):
    """
    Fetches Open Positions.
    """
    try:
        resp = dhan.get_positions()
        if resp['status'] == 'success':
            return resp['data']
        return []
    except Exception as e:
        logger.error(f"Error fetching positions (Dhan): {e}")
        return []

def place_order_api(dhan, params):
    """
    Places order. 
    Params need modification to match Dhan format!
    SmartAPI params: {'symboltoken': ..., 'transactiontype': 'BUY', ...}
    Dhan params: {security_id, transaction_type, quantity, order_type, ...}
    """
    try:
        # Converter logic (Caller usually passes SmartAPI style params, we need to adapt)
        # OR we change caller to match Dhan. Adapting here is safer for "Drop-in".
        
        dhan_txn_type = dhanhq.BUY if params.get('transactiontype') == 'BUY' else dhanhq.SELL
        dhan_order_type = dhanhq.MARKET if params.get('ordertype') == 'MARKET' else dhanhq.LIMIT
        dhan_product = dhanhq.INTRADAY if params.get('producttype') == 'INTRADAY' else dhanhq.CNC
        
        order_id = dhan.place_order(
            security_id=str(params.get('symboltoken')),
            exchange_segment=dhanhq.NSE,
            transaction_type=dhan_txn_type,
            quantity=int(params.get('quantity')),
            order_type=dhan_order_type,
            product_type=dhan_product,
            price=float(params.get('price', 0)),
            validity=dhanhq.DAY
        )
        
        if order_id['status'] == 'success':
            return order_id['data']['orderId']
        else:
            logger.error(f"Dhan Order Failed: {order_id.get('remarks')}")
            return None
            
    except Exception as e:
        logger.error(f"Error placing order (Dhan): {e}")
        return None

def fetch_holdings(dhan):
    """
    Fetches Current Holdings.
    """
    try:
        resp = dhan.get_holdings()
        if resp['status'] == 'success':
            return resp['data']
        return []
    except Exception as e:
        logger.error(f"Error fetching holdings (Dhan): {e}")
        return []

