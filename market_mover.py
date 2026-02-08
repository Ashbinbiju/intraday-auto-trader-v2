import requests
import logging

# Setup logging
logger = logging.getLogger("MarketMoverScanner")

MOVER_API_URL = "https://brkpoint.in/api/market-movers"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_market_movers(side_filter="Gainer"):
    """
    Fetches market movers from brkpoint.in and filters by side (Gainer/Looser).
    Default is 'Gainer' as per user request.
    """
    try:
        logger.info(f"Fetching Market Movers ({side_filter})...")
        response = requests.get(MOVER_API_URL, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Data is a list of dicts
        # Filter by 'side'
        # API returns "Looser" (sic), maybe "Gainer"?
        # Let's assume standard "Gainer" / "Looser".
        # But wait, the user's snippet showed "Looser".
        # We need to filter for Gainers.
        
        movers = []
        for stock in data:
            stock_side = stock.get("side", "")
            
            # Case-insensitive check
            if stock_side.lower() == side_filter.lower():
                 movers.append({
                     "symbol": stock.get("tradingsymbol"),
                     "ltp": stock.get("live_price"),
                     "change": stock.get("change_from_yest_close"),
                     "rank": stock.get("rank")
                 })
        
        # Sort by Rank (Ascending)
        movers.sort(key=lambda x: x['rank'])
        
        # Limit to Top 15 as per user request
        movers = movers[:15]
        
        logger.info(f"Fetched {len(movers)} {side_filter}s (Limit: 15).")
        return movers

    except Exception as e:
        logger.error(f"Error fetching market movers: {e}")
        return []

if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    gainers = fetch_market_movers("Gainer")
    print(f"Top 5 Gainers: {[m['symbol'] for m in gainers[:5]]}")
