"""Quick script to check Angel One account balance."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from angel_api_helper import get_session

session = get_session()
if not session:
    print("[FAIL] Failed to connect to Angel One.")
    exit(1)

print("[OK] Connected to Angel One")

# Fetch RMS Limits (contains balance info)
try:
    rms = session.rmsLimit()
    if rms and rms.get('status'):
        data = rms.get('data', {})
        print("\n--- Angel One Account Balance ---")
        print(f"  Available Cash:    Rs {float(data.get('availablecash', 0)):,.2f}")
        print(f"  Net Cash:          Rs {float(data.get('net', 0)):,.2f}")
        print(f"  Collateral:        Rs {float(data.get('collateral', 0)):,.2f}")
        print(f"  M2M Realized:      Rs {float(data.get('m2mrealized', 0)):,.2f}")
        print(f"  M2M Unrealized:    Rs {float(data.get('m2munrealized', 0)):,.2f}")
        print(f"  Utilized Debits:   Rs {float(data.get('utiliseddebits', 0)):,.2f}")
    else:
        print(f"[FAIL] RMS Limit fetch failed: {rms}")
except Exception as e:
    print(f"[FAIL] Error: {e}")

# Also fetch profile for confirmation
try:
    profile = session.getProfile(session.refresh_token)
    if profile and profile.get('status'):
        p = profile.get('data', {})
        print(f"\n--- Account Info ---")
        print(f"  Name:    {p.get('name', 'N/A')}")
        print(f"  Client:  {p.get('clientcode', 'N/A')}")
        print(f"  Email:   {p.get('email', 'N/A')}")
except Exception:
    pass
