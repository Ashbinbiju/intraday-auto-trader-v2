from SmartApi import SmartConnect
import pyotp
import logging
import pandas as pd
from datetime import datetime, timedelta
import requests
import time

logger = logging.getLogger(__name__)

def handle_api_error(data, context="API Call"):
    """
    Handles API errors by logging them and returning a descriptive message.
    """
    message = data.get('message', 'Unknown error')
    error_code = data.get('errorcode', 'N/A')
    
    full_msg = f"{context} Failed: {message} (Code: {error_code})"
    
    # Specific error messages for common issues
    known_errors = {
        "AB1000": "Invalid credentials or session expired.",
        "AB1001": "Invalid API Key.",
        "AB1002": "Invalid TOTP.",
        "AB1003": "Invalid Client ID.",
        "AB1004": "Invalid Password.",
        "AB2001": "Rate limit exceeded.",
        "AB2002": "Invalid request parameters.",
        "AB2003": "Internal server error.",
        "AB2004": "Service unavailable.",
        "AB2005": "Data not found."
    }
    known_error = known_errors.get(error_code)
    
    if known_error:
        full_msg += f" ({known_error})"
        
    logger.error(full_msg)
    return full_msg

def is_status_success(data):
    """
    Checks if API response status is True (Boolean or String).
    Angel One sometimes returns "status": "false" which evaluates to True in Python.
    """
    status = data.get('status')
    if status is True: return True
    if isinstance(status, str) and status.lower() == 'true': return True
    return False

# Configuration
API_KEY = "ruseeaBq" 
CLIENT_CODE = "AAAG399109"
PASSWORD = "1503"
TOTP_KEY = "OLRQ3CYBLPN2XWQPHLKMB7WEKI"

def get_smartapi_session():
    try:
        smartApi = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_KEY).now()
        data = smartApi.generateSession(CLIENT_CODE, PASSWORD, totp)
        
        if is_status_success(data):
            logger.info("SmartAPI Session Generated Successfully")
            # Attach tokens for WebSocket use
            smartApi.jwt_token = data['data']['jwtToken']
            smartApi.feed_token = data['data']['feedToken']
            smartApi.refresh_token = data['data']['refreshToken']
            return smartApi
        else:
            logger.error(f"Failed to generate session: {data['message']}")
            handle_api_error(data, "Login") # Use helper
            return None
    except Exception as e:
        logger.error(f"Error generating session: {e}")
        return None
def fetch_candle_data(smartApi, token, symbol, interval="FIFTEEN_MINUTE", days=5, retries=3, delay=1):
    """
    Fetches candle data with Retry logic.
    """
    # Standard format: %Y-%m-%d %H:%M
    to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    
    params = {
        "exchange": "NSE",
        "symboltoken": str(token),
        "interval": interval,
        "fromdate": from_date,
        "todate": to_date
    }
    
    for i in range(retries):
        try:
            data = smartApi.getCandleData(params)
            
            if is_status_success(data):
                if not data.get('data'):
                    return None
                
                df = pd.DataFrame(data['data'], columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
                df['datetime'] = pd.to_datetime(df['datetime'])
                
                # Conversion logic
                df['close'] = df['close'].astype(float)
                df['volume'] = df['volume'].astype(int)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                df['open'] = df['open'].astype(float)
                return df
            
            # Identify Rate Limit Errors
            msg = str(data.get('message', '')).lower()
            if "access rate" in msg or "access denied" in msg or (data.get('errorcode') == 'AB2001'):
                logger.warning(f"⚠️ SmartAPI Rate Limit hit (Candles). Retrying in {delay}s... ({i+1}/{retries})")
                time.sleep(delay)
                continue

            handle_api_error(data, f"Fetch Candles ({symbol})")
            return None

        except Exception as e:
            if "access rate" in str(e).lower() or "access denied" in str(e).lower():
                logger.warning(f"⚠️ Rate limit exception (Candles). Retrying in {delay}s... ({i+1}/{retries})")
                time.sleep(delay)
                continue
            logger.error(f"Error fetching Candles for {symbol}: {e}")
            return None
            
    return None


def load_instrument_map():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    try:
        logger.info("Downloading Instrument Map...")
        instruments = requests.get(url).json()
        token_map = {}
        for instr in instruments:
            # Filter for NSE Equity
            if instr.get('exch_seg') == 'NSE' and instr.get('symbol', '').endswith("-EQ"):
                clean_sym = instr['symbol'].replace('-EQ', '')
                token_map[clean_sym] = instr['token']
        logger.info(f"Loaded {len(token_map)} instruments.")
        return token_map
    except Exception as e:
        logger.error(f"Error loading instrument map: {e}")
        return {}

def fetch_all_orders(smartApi):
    """
    Fetches the complete Order Book.
    """
    try:
        data = smartApi.orderBook()
        if data and 'data' in data:
            return data['data'] # List of orders
        return []
    except Exception as e:
        logger.error(f"Error fetching Order Book: {e}")
        return []

def fetch_net_positions(smartApi, retries=3, delay=2):
    """
    Fetches Net Positions (Open positions) with Retry logic for Rate Limits.
    """
    for i in range(retries):
        try:
            data = smartApi.position()
            if is_status_success(data):
                # Return empty list if no positions exist
                return data.get('data') or []
            
            # Identify Rate Limit Errors
            msg = str(data.get('message', '')).lower()
            if "access rate" in msg or "access denied" in msg:
                logger.warning(f"⚠️ SmartAPI Rate Limit hit. Retrying in {delay}s... ({i+1}/{retries})")
                time.sleep(delay)
                continue

            handle_api_error(data, "Fetch Positions")
            return None
        except Exception as e:
            # Catch "Couldn't parse JSON" errors which happen on rate limit html responses
            if "access rate" in str(e).lower() or "access denied" in str(e).lower():
                logger.warning(f"⚠️ Rate limit exception. Retrying in {delay}s... ({i+1}/{retries})")
                time.sleep(delay)
                continue
            logger.error(f"Error fetching Positions: {e}")
            return None
    
    logger.error("🛑 Max retries reached for fetch_net_positions.")
    return None

def calculate_margin(smartApi, positions_list):
    """
    Calculates margin for a list of positions.
    positions_list example: [{ "symbol": "SBIN-EQ", "qty": 1, "token": "3045", "transactionType": "BUY" }]
    """
    try:
        url = "https://apiconnect.angelone.in/rest/secure/angelbroking/margin/v1/batch"
        
        # Prepare Payload
        api_positions = []
        for p in positions_list:
            api_positions.append({
                "exchange": "NSE",
                "qty": p['qty'],
                "price": 0,
                "productType": "INTRADAY",
                "orderType": "MARKET",
                "token": p['token'],
                "tradeType": p['transactionType']
            })

        payload = {
            "positions": api_positions
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-UserType': 'USER',
            'X-SourceID': 'WEB',
            'X-ClientLocalIP': '127.0.0.1', 
            'X-ClientPublicIP': '127.0.0.1', 
            'X-MACAddress': 'MAC_ADDRESS',
            'X-PrivateKey': API_KEY,
            'Authorization': f'Bearer {smartApi.jwt_token}'
        }

        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            resp_json = response.json()
            if resp_json['status']:
                return resp_json['data']
            else:
                handle_api_error(resp_json, "Calculate Margin")
                return None
        else:
            logger.error(f"Margin API Failed: {response.status_code} {response.text}")
            return None

    except Exception as e:
        logger.error(f"Error calculating margin: {e}")
        return None

def fetch_holdings(smartApi):
    """
    Fetches Equity Holdings.
    """
    try:
        url = "https://apiconnect.angelone.in/rest/secure/angelbroking/portfolio/v1/getHolding"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-UserType': 'USER',
            'X-SourceID': 'WEB',
            'X-ClientLocalIP': '127.0.0.1', 
            'X-ClientPublicIP': '127.0.0.1', 
            'X-MACAddress': 'MAC_ADDRESS',
            'X-PrivateKey': API_KEY,
            'Authorization': f'Bearer {smartApi.jwt_token}'
        }
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            if data['status']: return data['data']
            handle_api_error(data, "Fetch Holdings")
            return None
        logger.error(f"Fetch Holdings Failed: {res.text}")
        return None
    except Exception as e:
        logger.error(f"Error fetching holdings: {e}")
        return None

def fetch_all_holdings(smartApi):
    """
    Fetches All Holdings (Including Summary).
    """
    try:
        url = "https://apiconnect.angelone.in/rest/secure/angelbroking/portfolio/v1/getAllHolding"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-UserType': 'USER',
            'X-SourceID': 'WEB',
            'X-ClientLocalIP': '127.0.0.1', 
            'X-ClientPublicIP': '127.0.0.1', 
            'X-MACAddress': 'MAC_ADDRESS',
            'X-PrivateKey': API_KEY,
            'Authorization': f'Bearer {smartApi.jwt_token}'
        }
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            if data['status']: return data['data']
            handle_api_error(data, "Fetch All Holdings")
            return None
        logger.error(f"Fetch All Holdings Failed: {res.text}")
        return None
    except Exception as e:
        logger.error(f"Error fetching all holdings: {e}")
        return None

def convert_position(smartApi, payload):
    """
    Converts a position (e.g. Intraday -> Delivery).
    """
    try:
        url = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/convertPosition"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-UserType': 'USER',
            'X-SourceID': 'WEB',
            'X-ClientLocalIP': '127.0.0.1', 
            'X-ClientPublicIP': '127.0.0.1', 
            'X-MACAddress': 'MAC_ADDRESS',
            'X-PrivateKey': API_KEY,
            'Authorization': f'Bearer {smartApi.jwt_token}'
        }
        res = requests.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            data = res.json()
            if data['status']: return data
            handle_api_error(data, "Convert Position")
            return None
        logger.error(f"Convert Position Failed: {res.text}")
        return None
    except Exception as e:
        logger.error(f"Error converting position: {e}")
        return None

def calculate_brokerage(smartApi, orders_list):
    """
    Calculates Brokerage & Charges.
    """
    try:
        url = "https://apiconnect.angelone.in/rest/secure/angelbroking/brokerage/v1/estimateCharges"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-UserType': 'USER',
            'X-SourceID': 'WEB',
            'X-ClientLocalIP': '127.0.0.1', 
            'X-ClientPublicIP': '127.0.0.1', 
            'X-MACAddress': 'MAC_ADDRESS',
            'X-PrivateKey': API_KEY,
            'Authorization': f'Bearer {smartApi.jwt_token}'
        }
        
        payload = { "orders": orders_list }
        
        res = requests.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            data = res.json()
            if data['status']: return data['data']
            handle_api_error(data, "Calculate Brokerage")
            return None
        
        logger.error(f"Brokerage Calc Failed: {res.text}")
        return None
    except Exception as e:
        logger.error(f"Error calculating brokerage: {e}")
        return None

def place_order_api(smartApi, params):
    """
    Places an Order.
    """
    try:
        # SDK placeOrder expects params dict
        order_id = smartApi.placeOrder(params)
        return order_id
    except Exception as e:
        logger.error(f"Place Order Failed: {e}")
        return None

def modify_order_api(smartApi, params):
    """
    Modifies an Order.
    """
    try:
        res = smartApi.modifyOrder(params)
        return res
    except Exception as e:
        logger.error(f"Modify Order Failed: {e}")
        return None

def cancel_order_api(smartApi, order_id, variety="NORMAL"):
    """
    Cancels an Order.
    """
    try:
        res = smartApi.cancelOrder(order_id, variety)
        return res
    except Exception as e:
        logger.error(f"Cancel Order Failed: {e}")
        return None

def fetch_trade_book(smartApi):
    """
    Fetches Trade Book.
    """
    try:
        res = smartApi.tradeBook()
        if res and 'data' in res: return res['data']
        return []
    except Exception as e:
        logger.error(f"Fetch Trade Book Failed: {e}")
        return []

def get_ltp_data(smartApi, exchange, symbol, token):
    """
    Fetches LTP Data.
    """
    try:
        res = smartApi.ltpData(exchange, symbol, token)
        if res and 'data' in res: return res['data']
        return None
    except Exception as e:
        logger.error(f"Fetch LTP Failed: {e}")
        return None

def get_individual_order(smartApi, unique_order_id):
    """
    Fetches details of a specific order by Unique ID.
    Note: SDK might not have a direct method for this specific endpoint detail, using requests.
    """
    try:
        url = f"https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/details/{unique_order_id}"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-UserType': 'USER',
            'X-SourceID': 'WEB',
            'X-ClientLocalIP': '127.0.0.1', 
            'X-ClientPublicIP': '127.0.0.1', 
            'X-MACAddress': 'MAC_ADDRESS',
            'X-PrivateKey': API_KEY,
            'Authorization': f'Bearer {smartApi.jwt_token}'
        }
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            if data['status']: return data['data']
            handle_api_error(data, "Get Order Details") # Added logic
            return None
        return None
    except Exception as e:
        logger.error(f"Fetch Individual Order Failed: {e}")
        return None


def verify_order_status(smartApi, order_id, retries=5, delay=1):
    """
    Verifies if an order was successfully placed and is not Rejected.
    Returns: (is_success: bool, status: str, average_price: float)
    """
    if not order_id: return False, "NO_ID", 0.0
    
    # Handle Dry Run / Simulation
    if order_id is True or str(order_id).upper() == "DRY_RUN":
        return True, "DRY_RUN", 0.0
    
    for i in range(retries):
        try:
            # We fetch individual order details because orderBook can be large
            # However, SmartAPI SDK assumes fetching all. 
            # Let's try fetching individual order if possible, else fetch all.
            # Using our get_individual_order helper
            data = get_individual_order(smartApi, order_id)
            
            if not data:
                # Fallback to full order book scan
                all_orders = fetch_all_orders(smartApi)
                for order in all_orders:
                    if order.get('orderid') == order_id:
                        data = order
                        break
            
            if data:
                status = data.get('status', '').lower() # complete, open, rejected, cancelled
                avg_price = float(data.get('averageprice', 0.0))
                
                if status == 'rejected':
                    reason = data.get('text', 'Unknown Rejection')
                    return False, f"REJECTED: {reason}", 0.0
                
                if status == 'cancelled':
                    return False, "CANCELLED", 0.0
                
                if status == 'validation pending':
                    time.sleep(delay)
                    continue

                # Open or Complete is Good
                # Note: SmartAPI returns 'success' or 'complete'
                return True, status.upper(), avg_price
            
            time.sleep(delay)
            
        except Exception as e:
            logger.error(f"Error verifying order {order_id}: {e}")
            time.sleep(delay)
            
    return False, "TIMEOUT_VERIFY", 0.0
