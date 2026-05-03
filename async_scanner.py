import asyncio
import aiohttp
import logging
import pandas as pd
from datetime import datetime
from indicators import calculate_indicators, check_buy_condition
from utils import get_ist_now
from broker_router import fetch_candle_data, fetch_ltp

logger = logging.getLogger("AsyncScanner")
# Ensure logging output matches MainBot
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

class AsyncScanner:
    def __init__(self, jwt_token, smartApi=None, concurrency=50, timeout=3):
        self.jwt_token = jwt_token
        self.smartApi = smartApi # Store Dhan Object
        self.concurrency = concurrency 
        self.sem = None 
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def fetch_candle_data(self, session, symbol, token):
        """
        Fetches 5M candle data using the Dhan SDK.
        Run in ThreadPoolExecutor because the SDK is blocking.
        """
        if not self.smartApi:
            logger.error(f"❌ [Async] SmartAPI Object missing for {symbol}")
            return symbol, None

        loop = asyncio.get_running_loop()
        
        try:
            # Fetch 5M candles only (no 15M needed)
            df_5m = await loop.run_in_executor(
                None, 
                fetch_candle_data, 
                self.smartApi, 
                token, 
                symbol, 
                "FIVE_MINUTE",
                5
            )
            
            if df_5m is not None:
                return symbol, df_5m
            
            return symbol, None

        except Exception as e:
            logger.error(f"❌ [Async] Wrapper Error {symbol}: {e}")
            return symbol, None


    async def bounded_fetch(self, session, symbol, token):
        async with self.sem:
            return await self.fetch_candle_data(session, symbol, token)

    async def scan(self, stocks_list, token_map, index_memory=None):
        """
        Scans a list of stocks using simple VWAP + EMA20 entry condition.
        stocks_list: list of dicts [{'symbol': 'INFY', 'ltp': 1500}, ...]
        token_map: dict {'INFY': '1234'}
        """
        ACTIVE_SYMBOLS = [s.get('symbol') for s in stocks_list]
        
        # Subscribe to websocket for fast LTPs
        from main import ANGEL_WS
        if ANGEL_WS and ANGEL_WS.connected:
            tokens_to_track = [token_map.get(s) for s in ACTIVE_SYMBOLS if token_map.get(s)]
            ANGEL_WS.subscribe(tokens_to_track)
        logger.info(f"Starting Async Scan for {len(stocks_list)} stocks...")
        
        # Initialize Semaphore inside the loop to ensure Loop Affinity
        self.sem = asyncio.Semaphore(self.concurrency)
        
        signals = []
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = []
            
            # Rate Limiting: Process in smaller batches
            rate_limit_batch_size = 1
            rate_limit_delay = 0.6 # ~1.5 req/sec
            
            total_stocks = len(stocks_list)
            
            for i, stock in enumerate(stocks_list):
                symbol = stock['symbol']
                token = token_map.get(symbol)
                
                if token:
                    tasks.append(asyncio.create_task(self.bounded_fetch(session, symbol, token)))
                    
                    # Throttling Logic
                    if (i + 1) % rate_limit_batch_size == 0:
                        await asyncio.sleep(rate_limit_delay)
            
            # Process as they complete
            completed_count = 0
            rejection_stats = {"Data": 0, "Price": 0}
            
            for task in asyncio.as_completed(tasks):
                completed_count += 1
                if completed_count % 50 == 0:
                    logger.info(f"⏳ Processed {completed_count}/{total_stocks} stocks...")
                
                symbol, df_5m = await task
                
                if df_5m is None:
                    rejection_stats["Data"] += 1
                    continue

                try:
                    # Calculate indicators on 5M data
                    df_5m = calculate_indicators(df_5m)
                    
                    if df_5m is None or len(df_5m) < 2:
                        rejection_stats["Data"] += 1
                        continue
                    
                    # Simple buy condition: Price > VWAP AND Price > EMA20
                    buy_signal, message = check_buy_condition(df_5m)
                    
                    if buy_signal:
                        logger.info(f"✅ {symbol} PASSED: {message}")
                        
                        # Retrieve sector
                        stock_info = next((s for s in stocks_list if s['symbol'] == symbol), None)
                        sector_name = stock_info.get('sector', 'Unknown') if stock_info else "Unknown"
                        
                        # Fetch LIVE price from Dhan
                        live_ltp = 0.0
                        try:
                            current_token = token_map.get(symbol)
                            if current_token:
                                live_ltp = fetch_ltp(self.smartApi, current_token, symbol)
                            else:
                                logger.warning(f"⚠️ {symbol}: Token not found for LTP fetch")
                            if live_ltp is None or live_ltp == 0:
                                logger.error(f"❌ {symbol}: LTP_UNAVAILABLE. Skipping.")
                                continue

                        except Exception as e:
                            logger.error(f"❌ {symbol}: LTP fetch error: {e}. Skipping.")
                            continue

                        signals.append({
                            'symbol': symbol,
                            'price': live_ltp,
                            'message': message,
                            'sector': sector_name,
                            'time': get_ist_now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                    else:
                        rejection_stats["Price"] += 1

                except Exception as e:
                    logger.error(f"Processing Error {symbol}: {e}")
                    rejection_stats["Data"] += 1
                    continue
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Async Scan Completed in {duration:.2f}s. Found {len(signals)} signals.")
        logger.info(f"📊 Scan Stats: {rejection_stats}")
        return signals
