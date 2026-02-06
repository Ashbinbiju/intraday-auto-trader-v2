import logging
import pandas as pd
import os
from config import config_manager
from dhan_api_helper import get_dhan_session, load_dhan_instrument_map, fetch_candle_data

# Setup simple logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_login():
    print("--- Debug Config ---")
    print(f"CWD: {os.getcwd()}")
    print(f"Config Loaded Sections: {list(config_manager.config.keys()) if config_manager.config else 'None'}")
    
    if "credentials" in config_manager.config:
        print(f"Creds found: {list(config_manager.config['credentials'].keys())}")
        print(f"Client ID: {config_manager.config['credentials'].get('dhan_client_id')}")
        # Dont print full token for security, just length
        token = config_manager.config['credentials'].get('dhan_access_token', '')
        print(f"Access Token Length: {len(token)}")
    else:
        print("❌ 'credentials' section MISSING in loaded config!")
             
    print("\n--- Testing Dhan Login ---")
    dhan = get_dhan_session()
    if dhan:
        print("✅ Login Successful!")
        
        # Test 1: Fetch Holdings
        print("\n--- Testing Holdings Fetch ---")
        try:
            holdings = dhan.get_holdings()
            if holdings['status'] == 'success':
                 print(f"✅ Holdings Response Success! Count: {len(holdings.get('data', []))}")
            else:
                 print(f"❌ Holdings Response Failed: {holdings}")
        except Exception as e:
            print(f"❌ Holdings Exception: {e}")
        
        # Test 2: Instrument Map
        print("\n--- Testing Instrument Map Download ---")
        token_map = load_dhan_instrument_map()
        if token_map:
            print(f"✅ Token Map Loaded. Count: {len(token_map)}")
            
            # Test 3: Fetch Candle Data (Try generic symbol like 'SBIN-EQ' or 'NIFTY 50')
            # 'SBIN-EQ' is typical trading symbol in Dhan
            print("\n--- Testing Candle Fetch (SBIN-EQ) ---")
            idx_sym = "SBIN-EQ" 
            if idx_sym in token_map:
                token = token_map[idx_sym]
                print(f"Found Token for {idx_sym}: {token}")
                
                # Fetch 15 min data
                df = fetch_candle_data(dhan, token, idx_sym, "FIFTEEN_MINUTE", days=1)
                
                if df is not None and not df.empty:
                    print(f"✅ Candle Data Fetched! Rows: {len(df)}")
                    print(df.head())
                else:
                    print("❌ Candle Data Fetch Failed (Empty or Error)")
            else:
                print(f"❌ Could not find {idx_sym} in token map.")
    else:
        print("❌ Login Failed.")

if __name__ == "__main__":
    test_login()
