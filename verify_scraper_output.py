
import logging
from scraper import fetch_top_performing_sectors, fetch_stocks_in_sector

# Setup simple logging
logging.basicConfig(level=logging.INFO)

def verify_scraper():
    print("\n--- 🕵️‍♂️ Verifying Scraper Output Live ---\n")
    
    # 1. Fetch Sectors
    print("1. Fetching Top Sectors...")
    sectors = fetch_top_performing_sectors()
    
    if not sectors:
        print("❌ No sectors returned. API might be down or empty.")
        return

    print(f"✅ Found {len(sectors)} positive sectors.")
    
    # 2. Pick the top sector
    top_sector = sectors[0]
    print(f"   Top Sector: {top_sector['name']} (Key: {top_sector['key']})")
    
    # 3. Fetch Stocks for this sector
    print(f"\n2. Fetching Stocks for '{top_sector['name']}'...")
    stocks = fetch_stocks_in_sector(top_sector['key'])
    
    if not stocks:
        print("❌ No stocks found in this sector.")
        return

    print(f"✅ Found {len(stocks)} stocks.\n")
    
    # 4. Print the first 5 Symbols exactly as received
    print("--- RAW SYMBOLS RECEIVED (First 5) ---")
    for stock in stocks[:5]:
        print(f"👉 Symbol: '{stock['symbol']}'  |  LTP: {stock['ltp']}")
        
    print("\n--------------------------------------")
    print("If these look like 'TATASTEEL', 'INFY', etc., then we are good!")

if __name__ == "__main__":
    verify_scraper()
