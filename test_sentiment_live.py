import asyncio
import aiohttp
import logging
from smart_api_helper import API_KEY, CLIENT_CODE, get_smartapi_session

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SentimentTester")

async def test_sentiment():
    print("\n--- 🔍 Testing Market Sentiment (Sentinel Logic) ---\n")

    # 1. Login
    smartApi = get_smartapi_session()
    if not smartApi:
        print("❌ Login Failed")
        return

    jwt_token = smartApi.jwt_token
    print("✅ Login Successful. Fetching Index Data...")

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

    indices = [
        {"symbol": "NIFTY", "token": "26000"},
        {"symbol": "BANKNIFTY", "token": "26009"}
    ]
    
    base_url = "https://apiconnect.angelbroking.com"
    endpoint = "/rest/secure/angelbroking/market/v1/ltpData"

    bullish_count = 0
    
    # Use SDK Synchronous call for reliability in test script
    for idx in indices:
        try:
            print(f"   Fetching {idx['symbol']}...")
            data = smartApi.ltpData("NSE", idx["symbol"], idx["token"])
            
            if data and data.get('status'):
                info = data.get('data', {})
                ltp = info.get('ltp')
                high = info.get('high')
                low = info.get('low')
                
                print(f"\n📊 {idx['symbol']} Data:")
                print(f"   LTP : {ltp}")
                print(f"   High: {high}")
                print(f"   Low : {low}")
                
                if ltp and high and low:
                    if high == low:
                        print(f"   ⚠️ Dead Session (High=Low). Skipping.")
                        continue
                        
                    # Calculate Position
                    range_denominator = high - low
                    range_pos = (ltp - low) / range_denominator
                    
                    status = "🟢 BULLISH" if range_pos > 0.55 else "🔴 WEAK"
                    print(f"   Calculation: ({ltp} - {low}) / ({high} - {low})")
                    print(f"   Range Position: {range_pos:.4f} (Threshold: > 0.55)")
                    print(f"   Result: {status}")
                    
                    if range_pos > 0.55:
                        bullish_count += 1
                else:
                    print("   ❌ Incomplete Data")
            else:
                print(f"   ❌ API Failure: {data}")

        except Exception as e:
            print(f"   ❌ Error: {e}")

    print("\n------------------------------------------------")
    if bullish_count == 2:
        print("✅ FINAL VERDICT: BULLISH MODE (Extension Limit: 3.0%)")
    else:
        print("⚠️ FINAL VERDICT: SAFETY MODE (Extension Limit: 1.5%)")
    print("------------------------------------------------\n")

if __name__ == "__main__":
    asyncio.run(test_sentiment())
