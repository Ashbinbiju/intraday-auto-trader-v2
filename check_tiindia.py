import sys
import os
sys.path.append(os.getcwd())

from smart_api_helper import SmartApiHelper
from config import ConfigManager
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_tiindia():
    config = ConfigManager()
    api = SmartApiHelper(config.config)
    
    logger.info("Fetching Instrument List...")
    # This might take a few seconds
    token_map = await api.get_token_map()
    
    target_symbols = ["TIINDIA", "CROMPTON", "SBIN"]
    
    for symbol in target_symbols:
        token = token_map.get(symbol)
        if token:
            logger.info(f"✅ FOUND: {symbol} -> Token {token}")
        else:
            logger.error(f"❌ MISSING: {symbol} not found in token map!")
        # Try fuzzy search
        logger.info("Searching for similar names...")
        for key in token_map.keys():
            if "TIINDIA" in key:
                logger.info(f"   Found Check: {key} -> {token_map[key]}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(verify_tiindia())
