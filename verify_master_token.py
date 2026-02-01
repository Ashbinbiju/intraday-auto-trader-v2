import requests
import json
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_tokens_independent():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    logger.info(f"Downloading Master Scrip from {url}...")
    
    try:
        response = requests.get(url)
        data = response.json()
        logger.info(f"Downloaded {len(data)} instruments.")

        if len(data) > 0:
            logger.info(f"First Item Keys: {data[0].keys()}")
            logger.info(f"First Item Sample: {data[0]}")
        
        targets = ["TIINDIA", "CROMPTON", "SBIN", "RELIANCE"]
        found = {t: False for t in targets}
        
        for item in data:
            if item.get("symbol") in targets and item.get("exch_seg") == "NSE":
                symbol = item.get("symbol")
                token = item.get("token")
                logger.info(f"✅ FOUND in Master: {symbol} -> {token}")
                found[symbol] = True
        
        for t, was_found in found.items():
            if not was_found:
                logger.error(f"❌ MISSING in Master: {t}")
                
    except Exception as e:
        logger.error(f"Download or Parse Failed: {e}")

if __name__ == "__main__":
    verify_tokens_independent()
