import requests
import json
import logging
import time

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SECTOR_API_URL = "https://intradayscreener.com/api/indices/sectorData/1"
STOCK_API_URL_TEMPLATE = "https://intradayscreener.com/api/indices/index-constituents/{}/1?filter=cash"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://intradayscreener.com/sector-performance",
}

def fetch_top_performing_sectors():
    """
    Fetches sector performance data and returns the top performing sectors (positive change).
    """
    try:
        response = requests.get(SECTOR_API_URL, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        
        sectors = []
        labels = data.get("labels", [])
        datasets = data.get("datasets", [])
        keywords = data.get("keywords", [])
        
        if not labels or not datasets:
            logger.warning("No sector data found.")
            return []

        # Zip generic datasets (assuming first dataset is the % change as shown in user example)
        # User example: "datasets": [3.34, 1.16, ...] which matches the visual "NIFTY_IT 3.34%"
        percentages = datasets # It seems datasets is a flat list in the example

        for i, sector_name in enumerate(labels):
            pct_change = percentages[i]
            if pct_change > 0: # Filter for positive sectors
                # Use keyword if available, else label, for the next API call
                api_key = keywords[i] if i < len(keywords) else sector_name
                sectors.append({
                    "name": sector_name,
                    "key": api_key,
                    "change": pct_change
                })
        
        # Sort by percentage change descending
        sectors.sort(key=lambda x: x['change'], reverse=True)
        return sectors

    except Exception as e:
        logger.error(f"Error fetching sectors: {e}")
        return []

def fetch_stocks_in_sector(sector_key):
    """
    Fetches stocks for a given sector key.
    """
    url = STOCK_API_URL_TEMPLATE.format(sector_key)
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        
        stocks = []
        # Combine both index and non-index constituents as they are all part of the sector view
        constituents = data.get("indexConstituents", []) + data.get("nonIndexConstituents", [])
        
        seen_symbols = set()
        for stock in constituents:
            symbol = stock.get("symbol")
            if symbol and symbol not in seen_symbols:
                stocks.append({
                    "symbol": symbol,
                    "ltp": stock.get("ltp"),
                    "change": stock.get("changePct")
                })
                seen_symbols.add(symbol)
                
        return stocks

    except Exception as e:
        logger.error(f"Error fetching stocks for sector {sector_key}: {e}")
        return []

if __name__ == "__main__":
    print("Fetching Top Sectors...")
    top_sectors = fetch_top_performing_sectors()
    
    for sector in top_sectors:
        print(f"\nSector: {sector['name']} ({sector['change']}%)")
        print("Fetching stocks...")
        stocks = fetch_stocks_in_sector(sector['key'])
        
        # Print top 5 stocks in this sector
        for stock in stocks[:5]: 
            print(f"  - {stock['symbol']}: {stock['ltp']} ({stock['change']}%)")
        
        # Just do one sector for test
        break
