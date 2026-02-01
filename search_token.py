import requests
import json

url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
print("Downloading Master Scrip...")
r = requests.get(url)
data = r.json()

print("Searching for Nifty Indices...")
found = []
for item in data:
    # Search for Exact Nifty 50 and Bank Nifty Names
    name = item.get("name", "")
    symbol = item.get("symbol", "")
    segment = item.get("exchangesegment", "")
    
    # Remove Segment Filter to scout
    if "Nifty 50" in name or "NIFTY" == symbol:
            found.append(item)
    if "Nifty Bank" in name or "BANKNIFTY" == symbol:
            found.append(item)

print(f"Found {len(found)} items.")
for f in found:
    print(f"Symbol: {f.get('symbol')} | Token: {f.get('token')} | Segment: {f.get('exchangesegment')} | Name: {f.get('name')}")
