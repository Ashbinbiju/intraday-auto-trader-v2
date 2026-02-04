import requests
import json

# Download instrument map
url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
print("Downloading instrument map...")
instruments = requests.get(url, timeout=30).json()

# Filter for the problematic symbols
target_symbols = ['ASTERDM', 'NH', 'LALPATHLAB', 'TARSONS']

print(f"\nSearching for: {target_symbols}\n")
print("="*80)

for symbol in target_symbols:
    # Find all matches (NSE + Non-NSE)
    matches = [i for i in instruments if i.get('symbol', '').replace('-EQ', '') == symbol]
    
    print(f"\n[Symbol: {symbol}]")
    print(f"   Total Matches: {len(matches)}")
    
    for match in matches:
        print(f"   - Exchange: {match.get('exch_seg'):10} | Symbol: {match.get('symbol'):20} | Token: {match.get('token')}")
    
    # Check NSE-EQ specifically
    nse_eq = [i for i in matches if i.get('exch_seg') == 'NSE' and i.get('symbol', '').endswith('-EQ')]
    if nse_eq:
        print(f"   [OK] NSE-EQ Token: {nse_eq[0]['token']}")
    else:
        print(f"   [ERROR] No NSE-EQ match found!")

print("\n" + "="*80)
