    # Skipped: Evidence already obtained in Step 3077.
import aiohttp
import logging
from smart_api_helper import API_KEY, CLIENT_CODE, get_smartapi_session
from datetime import datetime
import pandas as pd

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IndexVerifier")

async def verify_indices():
    # 1. Login to get Token
    smartApi = get_smartapi_session()
    if not smartApi:
        print("Login Failed")
        return

    jwt_token = smartApi.jwt_token
    print("Login Successful. Testing Index Fetch...")

    # 2. Setup Headers
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': '127.0.0.1', 
        'X-ClientPublicIP': '127.0.0.1', 
        'X-MACAddress': 'MAC_ADDRESS',
        'X-PrivateKey': API_KEY,
        'Authorization': f'Bearer {jwt_token}'
    }

    combinations = [
        {"desc": "Nifty 26000 NSE", "token": "26000", "exchange": "NSE"},
        {"desc": "Nifty 99926000 NSE", "token": "99926000", "exchange": "NSE"},
        {"desc": "Bank 26009 NSE", "token": "26009", "exchange": "NSE"},
        {"desc": "Bank 99926009 NSE", "token": "99926009", "exchange": "NSE"},
    ]

    for combo in combinations:
        print(f"Testing ltpData for {combo['desc']}...")
        try:
            data = smartApi.ltpData(combo['exchange'], combo['desc'].split()[0], combo['token'])
            # ltpData signature: exchange, tradingsymbol, symboltoken. 
            # Actually SmartConnect wrapper might be different. 
            # Let's use getQuote (search) or ltpData.
            # Usually ltpData returns { ... }.
            if data and data.get('status'):
                 print(f"✅ SUCCESS: {combo['desc']} Works! Data: {data['data']}")
            else:
                 print(f"❌ FAILED: {combo['desc']} - {data}")
        except Exception as e:
            print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(verify_indices())
