import requests
import json

SECTOR_API_URL = "https://intradayscreener.com/api/indices/sectorData/1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://intradayscreener.com/sector-performance",
}

try:
    response = requests.get(SECTOR_API_URL, headers=HEADERS)
    data = response.json()
    
    print("Keys:", data.keys())
    print("Labels len:", len(data.get("labels", [])))
    print("Datasets len:", len(data.get("datasets", [])))
    print("Keywords len:", len(data.get("keywords", [])))
    
    labels = data.get("labels", [])
    datasets = data.get("datasets", [])
    keywords = data.get("keywords", [])
    
    print("\n--- First 5 Items ---")
    for i in range(min(5, len(labels))):
        print(f"Index {i}:")
        print(f"  Label: {labels[i]}")
        print(f"  Dataset (Pct?): {datasets[i]}")
        print(f"  Keyword: {keywords[i]}")

except Exception as e:
    print(f"Error: {e}")
