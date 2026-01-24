from scraper import fetch_market_indices
import logging

logging.basicConfig(level=logging.INFO)

print("Testing fetch_market_indices()...")
try:
    data = fetch_market_indices()
    print(f"Data received: {len(data)} items")
    for item in data[:3]:
        print(item)
except Exception as e:
    print(f"Error: {e}")
