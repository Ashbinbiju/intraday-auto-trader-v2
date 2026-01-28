import datetime

# Year 2026 NSE Holidays (Tentative/Example List)
# Users should update this list annually.
NSE_HOLIDAYS = [
    "2026-01-26", # Republic Day
    "2026-03-07", # Mahashivratri
    "2026-03-25", # Holi
    "2026-03-29", # Good Friday
    "2026-04-09", # Id-Ul-Fitr (Check actual)
    "2026-04-14", # Dr. Ambedkar Jayanti
    "2026-04-17", # Ram Navami
    "2026-05-01", # Maharashtra Day
    "2026-06-17", # Bakri Id (Check actual)
    "2026-07-17", # Muharram (Check actual)
    "2026-08-15", # Independence Day
    "2026-10-02", # Gandhi Jayanti
    "2026-10-20", # Dussehra
    "2026-11-09", # Diwali Laxmi Pujan (Often Special Trading)
    "2026-11-10", # Diwali Balipratipada
    "2026-11-25", # Gurunanak Jayanti
    "2026-12-25", # Christmas
]

# Special Dates where Market is OPEN despite being Weekend/Holiday
# Example: Budget Day (Feb 1), Diwali Muhurat Trading
SPECIAL_TRADING_DAYS = [
    "2026-02-01", # Example: Budget Day on Sunday
    "2026-11-09", # Example: Muhurat Trading
]

def is_market_open():
    """
    Checks if the market is open today.
    Returns: (is_open: bool, reason: str)
    """
    # Fix: Use IST for Market Check (Render is UTC)
    try:
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
        now = ist_now
    except Exception:
         now = datetime.datetime.now() # Fallback

    today_str = now.strftime("%Y-%m-%d")
    weekday = now.weekday() # 0=Mon, 6=Sun

    # 1. Check Special Trading Days (Overrides everything)
    if today_str in SPECIAL_TRADING_DAYS:
        return True, "Special Trading Day"

    # 2. Check NSE Holidays
    if today_str in NSE_HOLIDAYS:
        return False, "Market Holiday (NSE)"

    # 3. Check Weekends
    if weekday == 5: # Saturday
        return False, "Market Closed (Saturday)"
    
    if weekday == 6: # Sunday
        return False, "Market Closed (Sunday)"

    # 4. Optional: Time Check (Operating Hours 09:15 - 15:30)
    # We can handle time checks inside the loop or here. 
    # For now, we return True if it's a valid DAY. 
    # The main loop checks TRADING_END_TIME separately.

    return True, "Market Open"

def get_ist_now():
    """
    Returns current datetime in IST (UTC+5:30).
    """
    try:
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
        return ist_now
    except Exception:
        return datetime.datetime.now() # Fallback
