import asyncio
import aiohttp
import logging
import pandas as pd
from datetime import datetime
from indicators import calculate_indicators, check_buy_condition
from utils import get_ist_now
from smart_api_helper import API_KEY, CLIENT_CODE

logger = logging.getLogger("AsyncScanner")
# Ensure logging output matches MainBot
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

class AsyncScanner:
    def __init__(self, jwt_token, concurrency=50, timeout=3):
        self.jwt_token = jwt_token
        self.api_key = API_KEY
        self.client_code = CLIENT_CODE
        self.sem = asyncio.Semaphore(concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.base_url = "https://apiconnect.angelbroking.com"
        self.endpoint = "/rest/secure/angelbroking/historical/v1/getCandleData"
        
        # Headers matching SmartAPI SDK
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-UserType': 'USER',
            'X-SourceID': 'WEB',
            'X-ClientLocalIP': '127.0.0.1', 
            'X-ClientPublicIP': '127.0.0.1', 
            'X-MACAddress': 'MAC_ADDRESS',
            'X-PrivateKey': self.api_key,
            'Authorization': f'Bearer {self.jwt_token}'
        }

    async def fetch_candle_data(self, session, symbol, token):
        # Fetch 5 days to be safe for 20 EMA
        now = datetime.now()
        to_date = now.strftime("%Y-%m-%d %H:%M")
        from_date = (now - pd.Timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
        
        payload = {
            "exchange": "NSE",
            "symboltoken": str(token),
            "interval": "FIFTEEN_MINUTE",
            "fromdate": from_date,
            "todate": to_date
        }

        try:
            async with session.post(self.base_url + self.endpoint, json=payload, headers=self.headers) as response:
                if response.status == 200:
                    data = await response.json()
                    # Check for explicit True (bool or string)
                    status = data.get('status')
                    if status is True or str(status).lower() == 'true':
                        return symbol, data.get('data')
                return symbol, None
        except Exception as e:
            # logger.warning(f"Fetch Failed {symbol}: {e}") 
            return symbol, None

    async def bounded_fetch(self, session, symbol, token):
        async with self.sem:
            return await self.fetch_candle_data(session, symbol, token)

    async def scan(self, stocks_list, token_map):
        """
        Scans a list of stocks.
        stocks_list: list of dicts [{'symbol': 'INFY', 'ltp': 1500}, ...]
        token_map: dict {'INFY': '1234'}
        """
        start_time = datetime.now()
        logger.info(f"Starting Async Scan for {len(stocks_list)} stocks...")
        
        signals = []
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = []
            for stock in stocks_list:
                symbol = stock['symbol']
                token = token_map.get(symbol)
                if token:
                    tasks.append(self.bounded_fetch(session, symbol, token))
            
            # Process as they complete
            for task in asyncio.as_completed(tasks):
                symbol, raw_data = await task
                
                if raw_data:
                    try:
                        # Create DF
                        df = pd.DataFrame(raw_data, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
                        df['datetime'] = pd.to_datetime(df['datetime'])
                        
                        # Conversion
                        df['close'] = df['close'].astype(float)
                        df['volume'] = df['volume'].astype(int)
                        # df['high'] = df['high'].astype(float) # Not strictly needed for Buy Check but good for completion
                        df['open'] = df['open'].astype(float) # Needed for Green Candle Check
                        
                        # Indicators
                        df = calculate_indicators(df)
                        
                        # Check Buy Condition (Strict Closed Candle)
                        screener_ltp = 0.0 # Placeholder, indicator ignores it now
                        buy_signal, message = check_buy_condition(df, current_price=screener_ltp)
                        
                        if buy_signal:
                            logger.info(f"🚀 Signal Found: {symbol} - {message}")
                            
                            # Retrieve sector if available in passed list (Optimization: Lookup map)
                            stock_info = next((s for s in stocks_list if s['symbol'] == symbol), None)
                            sector_name = stock_info.get('sector', 'Unknown') if stock_info else "Unknown"
                            actual_ltp = stock_info['ltp'] if stock_info else 0.0

                            signals.append({
                                'symbol': symbol,
                                'price': actual_ltp,
                                'message': message,
                                'sector': sector_name,
                                'time': get_ist_now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            
                    except Exception as e:
                        # logger.error(f"Processing Error {symbol}: {e}")
                        continue

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Async Scan Completed in {duration:.2f}s. Found {len(signals)} signals.")
        return signals
