import requests

# Download instrument map
url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
print("Downloading instrument map...")
instruments = requests.get(url, timeout=30).json()

# Search for partial matches
search_terms = ['ASTER', 'NH', 'LALPATH', 'TARSONS']

print("\nSearching for partial matches...\n")
print("="*100)

for term in search_terms:
    print(f"\n[Searching for: {term}]")
    matches = [i for i in instruments if term.upper() in i.get('symbol', '').upper() and i.get('exch_seg') == 'NSE']
    
    if matches:
        print(f"   Found {len(matches)} matches:")
        for m in matches[:10]:  # Limit to first 10
            print(f"   - {m.get('symbol'):25} | Token: {m.get('token'):10} | Name: {m.get('name', 'N/A')}")
    else:
        print(f"   No matches found")

print("\n" + "="*100)
