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

    async def check_market_sentiment(self, session, index_memory=None):
        """
        Checks if Market (Nifty + BankNifty) is Bullish.
        Uses Sentinel-Grade "Position in Range" Logic with Local Memory.
        """
        indices = [
            {"symbol": "NIFTY", "token": "26000"},
            {"symbol": "BANKNIFTY", "token": "26009"}
        ]
        
        bullish_count = 0
        endpoint = "/rest/secure/angelbroking/market/v1/ltpData"
        today_date = datetime.now().date().isoformat()
        regime_details = []
        
        for idx in indices:
            symbol = idx["symbol"]
            try:
                payload = {
                    "exchange": "NSE",
                    "tradingsymbol": symbol,
                    "symboltoken": idx["token"]
                }
                async with session.post(self.base_url + endpoint, json=payload, headers=self.headers) as response:
                    data = await response.json()
                    status = data.get('status')
                    if status is True or str(status).lower() == 'true':
                        info = data.get('data', {})
                        ltp = info.get('ltp')
                        high = info.get('high')
                        low = info.get('low')
                        
                        source = "API"

                        # LOGIC: Check Memory if Data Incomplete
                        if index_memory is not None:
                            # 1. Update Memory if we have fresh valid data
                            if high and low and high > 0:
                                old_mem = index_memory.get(symbol)
                                if not old_mem or old_mem.get("date") != today_date:
                                    logger.info(f"[INDEX_MEMORY] {symbol} Initialized for {today_date}: H{high}/L{low}")
                                elif old_mem['high'] != high or old_mem['low'] != low:
                                    logger.info(f"[INDEX_MEMORY] {symbol} Updated: H{old_mem['high']}->{high} (source=API)")

                                index_memory[symbol] = {
                                    "high": high,
                                    "low": low,
                                    "date": today_date
                                }
                            # 2. Use Memory if current data is bad (but valid LTP exists)
                            elif (not high or high == 0) and ltp:
                                mem = index_memory.get(symbol)
                                if mem and mem.get("date") == today_date:
                                    high = mem["high"]
                                    low = mem["low"]
                                    source = "MEMORY"
                                    logger.warning(f"[DATA_WARNING] {symbol} High/Low=0.0 -> Using Cached Memory (H{high}/L{low})")

                        if ltp and high and low:
                            # Edge Case: Dead Session
                            if high == low:
                                regime_details.append(f"{symbol}:DEAD_SESSION")
                                continue

                            # Calculate Position
                            numerator = ltp - low
                            denominator = high - low
                            if denominator == 0: continue
                            
                            range_pos = numerator / denominator
                            regime_details.append(f"{symbol} pos={range_pos:.2f}")
                            
                            if range_pos > 0.55:
                                bullish_count += 1
                        else:
                             regime_details.append(f"{symbol}:INCOMPLETE({source})")
            except Exception as e:
                logger.warning(f"Failed to check sentiment for {symbol}: {e}")
        
        # Final Decision
        if bullish_count == 2:
            logger.info(f"[REGIME] {' '.join(regime_details)} -> TREND_MODE (EXT=3.0)")
            return 3.0
        else:
            reason = "WEAK_RANGE" if len(regime_details) == 2 else "DATA_ISSUE"
            logger.info(f"[REGIME] {' '.join(regime_details)} -> SAFETY_MODE (EXT=1.5) reason={reason}")
            return 1.5

    async def scan(self, stocks_list, token_map, index_memory=None):
        """
        Scans a list of stocks.
        stocks_list: list of dicts [{'symbol': 'INFY', 'ltp': 1500}, ...]
        token_map: dict {'INFY': '1234'}
        index_memory: dict for caching index high/low
        """
        start_time = datetime.now()
        logger.info(f"Starting Async Scan for {len(stocks_list)} stocks...")
        
        signals = []
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            
            # Step 1: Check Market Sentiment (Dynamic Limit)
            extension_limit = await self.check_market_sentiment(session, index_memory)
            
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
                        buy_signal, message = check_buy_condition(df, current_price=screener_ltp, extension_limit=extension_limit)
                        
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
                        else:
                            # Log specific rejection reasons for debugging (like Extension Limit)
                            if "Extension" in message or "Late Entry" in message:
                                regime = "TREND" if extension_limit == 3.0 else "SAFETY"
                                logger.info(f"[ENTRY_GUARD] {symbol} skipped: {message} (REGIME={regime})")
                            
                    except Exception as e:
                        logger.error(f"Processing Error {symbol}: {e}")
                        continue

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Async Scan Completed in {duration:.2f}s. Found {len(signals)} signals.")
        return signals
