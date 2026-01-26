
import logging
from smart_api_helper import load_instrument_map

# Setup simple logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TokenTester")

def test_lookup():
    print("\n--- Testing Token Lookup Logic ---")
    
    # 1. Load the Master Map
    print("1. Downloading and processing Master Script from Angel One...")
    token_map = load_instrument_map()
    
    if not token_map:
        print("❌ Failed to load token map.")
        return

    # 2. Test common symbols
    test_symbols = ["TATASTEEL", "RELIANCE", "INFY", "ZOMATO", "HDFCBANK"]
    
    print(f"\n2. Testing lookup for: {test_symbols}\n")
    
    for symbol in test_symbols:
        token = token_map.get(symbol)
        if token:
            print(f"✅ {symbol} found! -> Token: {token}")
        else:
            print(f"❌ {symbol} NOT found in NSE Equity map.")
    
    print("\n--- Test Complete ---")

if __name__ == "__main__":
    test_lookup()
