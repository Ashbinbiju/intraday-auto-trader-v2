import asyncio
import aiohttp
import logging
import pandas as pd
from datetime import datetime
from indicators import calculate_indicators, check_buy_condition
from utils import get_ist_now
from dhan_api_helper import fetch_candle_data, fetch_ltp

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
        # self.api_key = API_KEY # Obsolete
        # self.client_code = CLIENT_CODE # Obsolete
        self.concurrency = concurrency 
        self.sem = None 
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.base_url = "https://api.dhan.co" # Updated
        self.endpoint = "" # Not used with SDK
        
        # Headers not needed for SDK wrapper, but kept empty for safety if logic checks it
        self.headers = {}

    async def fetch_candle_data(self, session, symbol, token):
        """
        Delegates data fetching to the robust smart_api_helper function.
        Run in ThreadPoolExecutor because smartApi.getCandleData is blocking.
        """
        # We don't use 'session' (aiohttp) anymore, we use self.smartApi (SmartConnect Object)
        if not self.smartApi:
            logger.error(f"❌ [Async] SmartAPI Object missing for {symbol}")
            return symbol, None

        loop = asyncio.get_running_loop()
        
        try:
            # Call the Verified Helper Function (Blocking)
            # Fetch BOTH 15M (bias) and 5M (entry) for multi-timeframe confluence
            loop = asyncio.get_event_loop()
            
            # Fetch 15M for trend bias/direction
            df_15m = await loop.run_in_executor(
                None, 
                fetch_candle_data, 
                self.smartApi, 
                token, 
                symbol, 
                "FIFTEEN_MINUTE",
                5
            )
            
            # Fetch 5M for precise entry signal
            df_5m = await loop.run_in_executor(
                None, 
                fetch_candle_data, 
                self.smartApi, 
                token, 
                symbol, 
                "FIVE_MINUTE",
                5
            )
            
            if df_15m is not None and df_5m is not None:
                # Return both as tuple
                return symbol, (df_15m, df_5m)
            
            return symbol, None

        except Exception as e:
            logger.error(f"❌ [Async] Wrapper Error {symbol}: {e}")
            return symbol, None


    async def bounded_fetch(self, session, symbol, token):
        async with self.sem:
            return await self.fetch_candle_data(session, symbol, token)

    async def check_market_sentiment(self, session, index_memory=None):
        """
        Checks if Market (Nifty + BankNifty) is Bullish.
        Uses 'brkpoint.in' API for reliable Sentinel Data.
        """
        bullish_count = 0
        endpoint = "https://brkpoint.in/api/indexscan"
        today_date = datetime.now().date().isoformat()
        regime_details = []
        
        try:
            # External API Call
            async with session.get(endpoint) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Map API Response to our Logic
                    # Need NIFTY 50 and Bank NIFTY
                    target_indices = {
                        "NIFTY 50": "NIFTY",
                        "Bank NIFTY": "BANKNIFTY"
                    }
                    
                    found_indices = 0
                    
                    for item in data:
                        api_name = item.get("index")
                        symbol = target_indices.get(api_name)
                        
                        if symbol:
                            found_indices += 1
                            ltp = item.get("price")
                            # Use today_15m_high/low as proxy for Day High/Low (Robust source)
                            high = item.get("today_15m_high")
                            low = item.get("today_15m_low")
                            
                            # Fallback if 15m keys missing, try others or fail safe
                            if not high or not low:
                                high = item.get("prev_day_high") # Safety Fallback if today's data is null (rare)
                                low = item.get("prev_day_low")

                            if not ltp or not high or not low:
                                regime_details.append(f"{symbol}:BAD_DATA")
                                continue

                            # Update Memory (for logging consistency/backup mostly)
                            if index_memory is not None:
                                index_memory[symbol] = {
                                    "high": high,
                                    "low": low,
                                    "date": today_date
                                }

                            # Edge Case: Dead Session
                            if high == low:
                                regime_details.append(f"{symbol}:DEAD_SESSION")
                                continue

                            # Calculate Position
                            numerator = ltp - low
                            denominator = high - low
                            
                            if denominator == 0: 
                                continue
                            
                            range_pos = numerator / denominator
                            regime_details.append(f"{symbol} pos={range_pos:.2f}")
                            
                            if range_pos > 0.55:
                                bullish_count += 1
                    
                    if found_indices < 2:
                        logger.warning("External API did not return both indices.")
                        return 0.8 # Safety Mode Fallback
                        
                else:
                    logger.warning(f"External API Failed: {response.status}")
                    return 0.8

        except Exception as e:
            logger.error(f"Sentiment Check Failed: {e}")
            return 0.8
        
        # Final Decision
        if bullish_count == 2:
            logger.info(f"[REGIME] {' '.join(regime_details)} -> TREND_MODE (EXT=2.0)")
            return 2.0
        else:
            # Stricter Safety Mode to avoid chasing (0.8%)
            reason = "WEAK_RANGE" if len(regime_details) >= 1 else "DATA_ISSUE"
            logger.info(f"[REGIME] {' '.join(regime_details)} -> SAFETY_MODE (EXT=0.8) reason={reason}")
            return 0.8
        


    async def scan(self, stocks_list, token_map, index_memory=None):
        """
        Scans a list of stocks.
        stocks_list: list of dicts [{'symbol': 'INFY', 'ltp': 1500}, ...]
        token_map: dict {'INFY': '1234'}
        index_memory: dict for caching index high/low
        """
        start_time = datetime.now()
        logger.info(f"Starting Async Scan for {len(stocks_list)} stocks...")
        
        # Initialize Semaphore inside the loop to ensure Loop Affinity
        self.sem = asyncio.Semaphore(self.concurrency)
        
        signals = []
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            
            # Step 1: Check Market Sentiment (Dynamic Limit)
            extension_limit = await self.check_market_sentiment(session, index_memory)
            logger.info(f"⚡ SENTINEL DEBUG ACTIVE ⚡ - Market Check Done. Ext Limit: {extension_limit}")

            tasks = []
            
            # Rate Limiting: Process in smaller batches
            # Dhan Rate Limit is aggressive for historical data (DH-904).
            # Dropping from 3/sec to 1/sec + delay.
            
            rate_limit_batch_size = 1
            rate_limit_delay = 0.6 # Slower but safer (Approx 1.5 req/sec)
            
            total_stocks = len(stocks_list)
            
            for i, stock in enumerate(stocks_list):
                symbol = stock['symbol']
                token = token_map.get(symbol)
                
                if token:
                    # Fire Request
                    tasks.append(asyncio.create_task(self.bounded_fetch(session, symbol, token)))
                    
                    # Throttling Logic
                    if (i + 1) % rate_limit_batch_size == 0:
                        await asyncio.sleep(rate_limit_delay)
            
            # Process as they complete (Tasks are already running from loop above)
            completed_count = 0
            rejection_stats = {"Bias": 0, "Price": 0, "Wait": 0, "Data": 0}
            
            for task in asyncio.as_completed(tasks):
                completed_count += 1
                if completed_count % 50 == 0:
                    logger.info(f"⏳ Processed {completed_count}/{total_stocks} stocks...")
                
                symbol, raw_data = await task
                
                # Check for None (Failed Fetch)
                if raw_data is None:
                    rejection_stats["Data"] += 1
                    continue

                if raw_data is not None:
                    try:
                        # raw_data is now a tuple: (df_15m, df_5m)
                        if isinstance(raw_data, tuple) and len(raw_data) == 2:
                            df_15m, df_5m = raw_data
                            # logger.info(f"[DEBUG_DATA] {symbol}: ✅ Fetched 15M ({len(df_15m)}) + 5M ({len(df_5m)}) candles")
                            
                            # Import check_15m_bias
                            from indicators import check_15m_bias
                            
                            # Step 1: Check 15M Bias (The Golden Rule)
                            df_15m = calculate_indicators(df_15m)
                            bias_15m, bias_reason = check_15m_bias(df_15m)
                            
                            # REJECT if 15M is not BULLISH
                            if bias_15m != 'BULLISH':
                                # logger.info(f"❌ {symbol} REJECTED: {bias_reason}") # Removed to reduce spam
                                rejection_stats["Bias"] += 1
                                continue
                            
                            
                            # Step 2: Check 5M Entry Signal
                            df_5m = calculate_indicators(df_5m)
                            screener_ltp = 0.0
                            buy_signal, message = check_buy_condition(df_5m, current_price=screener_ltp, extension_limit=extension_limit)
                            
                            if buy_signal:
                                logger.info(f"✅ {symbol} PASSED: {bias_reason} | 5M: {message}")
                                
                                # Retrieve sector
                                stock_info = next((s for s in stocks_list if s['symbol'] == symbol), None)
                                sector_name = stock_info.get('sector', 'Unknown') if stock_info else "Unknown"
                                
                                # FIX: Fetch LIVE price from Angel One instead of using stale scraper price
                                live_ltp = 0.0
                                try:
                                    from dhan_api_helper import fetch_ltp
                                    # Fix: Re-fetch token for the CURRENT symbol!
                                    current_token = token_map.get(symbol)
                                    if current_token:
                                        live_ltp = fetch_ltp(self.smartApi, current_token, symbol)
                                    else:
                                        logger.warning(f"⚠️ {symbol}: Token not found for LTP fetch")
                                    if live_ltp is None or live_ltp == 0:
                                        # Fallback to scraper price if Dhan API fails
                                        live_ltp = stock_info['ltp'] if stock_info else 0.0
                                        logger.warning(f"⚠️ {symbol}: Using scraper price (Dhan LTP failed)")
                                except Exception as e:
                                    logger.error(f"❌ {symbol}: LTP fetch error: {e}")
                                    live_ltp = stock_info['ltp'] if stock_info else 0.0

                                # Add signal (MUST be inside if buy_signal block)
                                signals.append({
                                    'symbol': symbol,
                                    'price': live_ltp,  # Now using LIVE price from Dhan
                                    'message': message,
                                    'sector': sector_name,
                                    'time': get_ist_now().strftime("%Y-%m-%d %H:%M:%S")
                                })
                            else:
                                rejection_stats["Price"] += 1
                                # Log "Interesting" rejections (Close > EMA20) to filter noise
                                last_row = df_5m.iloc[-1]
                                close_p = last_row['close']
                                ema_20 = last_row.get('EMA_20', 0)
                                if close_p > ema_20:
                                    ext_pct = ((close_p - ema_20) / ema_20) * 100 if ema_20 > 0 else 0
                                    logger.info(f"[DEBUG_REJECT] {symbol}: Msg='{message}' | Ext={ext_pct:.2f}%")

                    except Exception as e:
                        logger.error(f"Processing Error {symbol}: {e}")
                        rejection_stats["Wait"] += 1 # Count processing errors as 'Other/Wait'
                        continue
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Async Scan Completed in {duration:.2f}s. Found {len(signals)} signals.")
        logger.info(f"📊 Scan Stats: {rejection_stats}")
        return signals
