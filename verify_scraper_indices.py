from scraper import fetch_market_indices

print("Fetching Market Indices from Scraper...")
indices = fetch_market_indices()

found = False
for idx in indices:
    if idx['symbol'] in ['NIFTY', 'BANKNIFTY']:
        print(f"\nIndex: {idx['symbol']}")
        print(f"LTP: {idx.get('ltp')}")
        # Note: Scraper might use different keys, checking raw dict
        print(f"Raw: {idx}")
        found = True

if not found:
    print("Indices not found in scraper output.")
