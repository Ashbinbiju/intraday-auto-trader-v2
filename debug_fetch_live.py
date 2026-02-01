
import logging
import sys
import os
import asyncio
import pandas as pd
from datetime import datetime

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add path
sys.path.append(os.getcwd())

# Import FUNCTIONS directly
from smart_api_helper import fetch_candle_data, load_instrument_map, get_smartapi_session

def test_fetch():
    logger.info("--- Starting Standalone Fetch Test ---")
    
    # 1. Initialize Session
    logger.info("Initializing SmartAPI Session...")
    smartApi = get_smartapi_session()
    
    if not smartApi:
        logger.error("Failed to get Session!")
        return

    # 2. Load Map
    logger.info("Loading Token Map...")
    token_map = load_instrument_map()
    logger.info(f"Loaded {len(token_map)} instruments.")
    
    # 3. Test Stocks
    targets = ["SBIN", "M&M", "CROMPTON", "RELIANCE"]
    
    for sym in targets:
        token = token_map.get(sym)
        if not token:
            logger.error(f"❌ Token NOT FOUND for {sym}")
            continue
            
        logger.info(f"Fetching Data for {sym} (Token: {token})...")
        
        # 4. Fetch (Synchronous/Blocking call to helper function)
        try:
            # Note: smartApi object is passed as first argument
            df = fetch_candle_data(smartApi, token, sym, interval="FIVE_MINUTE", days=4)
            
            if df is not None and not df.empty:
                logger.info(f"✅ SUCCESS {sym}: Fetched {len(df)} candles.")
                logger.info(f"Last Candle: {df.iloc[-1].to_dict()}")
            else:
                logger.error(f"❌ FAILURE {sym}: Returned None/Empty.")
                
        except Exception as e:
            logger.error(f"❌ EXCEPTION {sym}: {e}")

if __name__ == "__main__":
    test_fetch()
