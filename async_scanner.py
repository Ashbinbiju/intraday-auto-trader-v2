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
    def __init__(self, jwt_token, smartApi=None, concurrency=50, timeout=3):
        self.jwt_token = jwt_token
        self.smartApi = smartApi # Store SmartAPI Object
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
            # Signature: fetch_candle_data(smartApi, token, symbol, interval, days, retries, delay)
            df = await loop.run_in_executor(
                None, 
                fetch_candle_data, 
                self.smartApi, 
                token, 
                symbol, 
                "FIFTEEN_MINUTE", 
                5, 3, 1 # Default params
            )
            
            if df is not None and not df.empty:
                # Success! Return DF directly.
                return symbol, df
            
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
                        return 1.5 # Safety
                        
                else:
                    logger.warning(f"External API Failed: {response.status}")
                    return 1.5

        except Exception as e:
            logger.error(f"Sentiment Check Failed: {e}")
            return 1.5
        
        # Final Decision
        if bullish_count == 2:
            logger.info(f"[REGIME] {' '.join(regime_details)} -> TREND_MODE (EXT=3.0)")
            return 3.0
        else:
            reason = "WEAK_RANGE" if len(regime_details) >= 1 else "DATA_ISSUE"
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
            logger.info(f"⚡ SENTINEL DEBUG ACTIVE ⚡ - Market Check Done. Ext Limit: {extension_limit}")

            tasks = []
            
            # Rate Limiting: Process in batches or with delay
            # Angel One Rate Limit is approx 3 requests per second for Historical Data.
            # We have 176 stocks. Firing all at once gets us banned (AB2001).
            # Strategy: Fire 3 requests, wait 1 second.
            
            rate_limit_batch_size = 3
            rate_limit_delay = 1.0 # 1 Second constraint
            
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
            for task in asyncio.as_completed(tasks):
                symbol, raw_data = await task
                
                # Check for None (Failed Fetch)
                if raw_data is None:
                    continue

                if raw_data is not None:
                    # Check if it's already a DataFrame (from smart_api_helper delegator)
                    if isinstance(raw_data, pd.DataFrame):
                        df = raw_data
                        logger.info(f"[DEBUG_DATA] {symbol}: ✅ Fetched {len(df)} candles")
                    
                    # Legacy fallback (list of lists) - kept just in case
                    elif isinstance(raw_data, list):
                        logger.info(f"[DEBUG_DATA] {symbol}: ✅ Fetched {len(raw_data)} candles (List)")
                        try:
                            df = pd.DataFrame(raw_data, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
                            df['datetime'] = pd.to_datetime(df['datetime'])
                            # Conversion
                            df['close'] = df['close'].astype(float)
                            df['volume'] = df['volume'].astype(int)
                            df['open'] = df['open'].astype(float)
                        except Exception as e:
                            logger.error(f"DataFrame Conversion Failed for {symbol}: {e}")
                            continue
                    else:
                        logger.warning(f"[DEBUG_DATA] {symbol}: ❌ Unknown Data Format: {type(raw_data)}")
                        continue
                        
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
                            # Log ALL rejections for debugging (since we have 0 signals)
                            # To avoid log spam in production, we can condense this later.
                            last_row = df.iloc[-1]
                            close_p = last_row['close']
                            ema_20 = last_row['EMA_20']
                            rsi_val = last_row['RSI']
                            
                            # Only log "Interesting" rejections (Close > EMA20) to filter noise
                            if close_p > ema_20:
                                ext_pct = ((close_p - ema_20) / ema_20) * 100
                                logger.info(f"[DEBUG_REJECT] {symbol}: Msg='{message}' | Close={close_p:.2f} EMA={ema_20:.2f} RSI={rsi_val:.1f} Ext={ext_pct:.2f}%")

                            
                    except Exception as e:
                        logger.error(f"Processing Error {symbol}: {e}")
                        continue

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Async Scan Completed in {duration:.2f}s. Found {len(signals)} signals.")
        return signals
