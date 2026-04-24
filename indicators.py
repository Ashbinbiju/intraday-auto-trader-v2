import pandas as pd

def calculate_indicators(df):
    """
    Calculates VWAP and EMA 20 using standard Pandas.
    Expects df to have columns: datetime, open, high, low, close, volume
    """
    if df is None or len(df) < 20:
        return None
    
    # EMA 20
    df['EMA_20'] = df['close'].ewm(span=20, adjust=False).mean()
    
    # VWAP (Intraday / Cumulative)
    # Standard formula: Cumulative(Volume * TypicalPrice) / Cumulative(Volume)
    # This calculates a "Rolling" VWAP from the start of the fetched data.
    # Since we strictly fetch 10 days of 15 min data, this might be a multi-day VWAP.
    # To act like an Intraday VWAP, we should group by Day.
    
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
    df['vp'] = df['volume'] * df['typical_price']
    
    # Group by Date to reset VWAP each day (Standard Intraday VWAP)
    # Check if 'datetime' is column or index
    if 'datetime' in df.columns:
        date_series = df['datetime'].dt.date
    else:
        date_series = df.index.date

    df['VWAP'] = df.groupby(date_series)['vp'].cumsum() / df.groupby(date_series)['volume'].cumsum()
    
    # Volume SMA 20
    df['Volume_SMA_20'] = df['volume'].ewm(span=20, adjust=False).mean()
    
    # ATR 14 Calculation (Manual TR) for Dynamic SL
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR'] = tr.ewm(span=14, adjust=False).mean()

    return df


def check_buy_condition(df, current_price=None):
    """
    Simple entry condition: Price > VWAP AND Price > EMA 20.
    Uses the last confirmed candle (iloc[-2]) to avoid repainting.
    Returns: (bool, str)
    """
    if df is None or df.empty:
        return False, "No Data"

    if len(df) < 2:
        return False, "Not enough data"
        
    last_row = df.iloc[-2]
    
    ema_20 = last_row.get('EMA_20')
    vwap = last_row.get('VWAP')
    close_price = last_row.get('close')
    
    if pd.isna(ema_20) or pd.isna(vwap):
        return False, "Not enough data for indicators"
    
    if close_price <= vwap:
        return False, f"Price below VWAP ({close_price:.2f} <= {vwap:.2f})"
    
    if close_price <= ema_20:
        return False, f"Price below EMA20 ({close_price:.2f} <= {ema_20:.2f})"
    
    return True, f"Strong Buy: Price {close_price:.2f} > VWAP {vwap:.2f} & EMA20 {ema_20:.2f}"


def calculate_sr_levels(df):
    """
    Calculates Previous Day High/Low (PDH, PDL) and Current Day High/Low (CDH, CDL).
    Expects df to have 'datetime', 'high', 'low' columns.
    Returns dict or None if insufficient data.
    """
    if df is None or df.empty:
        return None
        
    try:
        # Avoid SettingWithCopyWarning
        df = df.copy()
        
        # Ensure datetime is datetime object
        if 'datetime' not in df.columns:
             if isinstance(df.index, pd.DatetimeIndex):
                 df = df.reset_index()
             else:
                 return None
             
        # Check if actually datetime64
        if not pd.api.types.is_datetime64_any_dtype(df['datetime']):
             df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
        
        # Drop rows where datetime parsing failed
        df = df.dropna(subset=['datetime'])
             
        df['date'] = df['datetime'].dt.date
        
        # Group by Date to get Daily Highs/Lows
        daily_ohlc = df.groupby('date').agg({'high': 'max', 'low': 'min'})
        
        if len(daily_ohlc) < 2:
            return None # Need at least 2 days (Prev + Current)
            
        # Get Previous Day (Second Last Row) 
        # Note: If current day is partial, it's the last row. Previous day is second last.
        prev_day = daily_ohlc.iloc[-2]
        curr_day = daily_ohlc.iloc[-1]
        
        # Date Validation: Ensure 'curr_day' is actually TODAY
        import datetime
        # Use IST (UTC+5:30) for date check
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        ist_now_date = (utc_now + datetime.timedelta(hours=5, minutes=30)).date()
        
        curr_day_date = curr_day.name # Groupby key is index
        
        pdh = prev_day['high']
        pdl = prev_day['low']
        cdh = None
        cdl = None
        
        if curr_day_date == ist_now_date:
            cdh = curr_day['high']
            cdl = curr_day['low']
        else:
            # Data ends at yesterday (Pre-market or early morning)
            # So "curr_day" in the DF is actually Yesterday, and "prev_day" is Day Before Yesterday.
            # We must shift logic.
            pdh = curr_day['high'] # Yesterday becomes PDH
            pdl = curr_day['low']  # Yesterday becomes PDL
            # CDH/CDL remains None (No data for today yet)
            
        return {
            "PDH": pdh,
            "PDL": pdl,
            "CDH": cdh,
            "CDL": cdl
        }
    except Exception as e:
        # Logging not available here
        return None

def get_dynamic_sr_levels(df, prd=10, max_pivots=20, channel_w_pct=10, max_sr=5, min_strength=2):
    """
    Translates TradingView Auto-Pivot Support/Resistance Logic.
    Returns a list of dicts with 'hi', 'lo', 'mid', 'strength'.
    """
    if df is None or len(df) < prd * 2:
        return []
        
    df = df.copy()
    
    # Calculate rolling highest/lowest for channel width calculation (300 bars)
    prd_highest = df['high'].rolling(300, min_periods=1).max().iloc[-1]
    prd_lowest = df['low'].rolling(300, min_periods=1).min().iloc[-1]
    
    # 1. Identify Pivot Highs and Lows
    # A pivot is a local max/min over a window of 2*prd + 1
    df['roll_high'] = df['high'].rolling(window=2*prd+1, center=True).max()
    df['roll_low'] = df['low'].rolling(window=2*prd+1, center=True).min()
    
    # Extract Pivot bars
    pivot_bars = df[(df['high'] == df['roll_high']) | (df['low'] == df['roll_low'])]
    
    pivots = []
    # Match chronological order
    for _, row in pivot_bars.iterrows():
        if row['high'] == row['roll_high']:
            pivots.append(row['high'])
        if row['low'] == row['roll_low']:
            pivots.append(row['low'])
            
    # Keep only the last `max_pivots` (e.g. 20)
    pivots = pivots[-max_pivots:]
    
    # Reverse to process most recent first (matching TV array.unshift behavior)
    pivots.reverse()
    
    # 2. Channel Width for Clustering
    cwidth = (prd_highest - prd_lowest) * channel_w_pct / 100.0
    
    sr_levels = []
    
    # 3. Cluster Pivots into S/R Zones
    for i in range(len(pivots)):
        lo = pivots[i]
        hi = pivots[i]
        numpp = 0
        
        # Calculate cluster boundaries and count pivots inside
        for j in range(len(pivots)):
            cpp = pivots[j]
            wdth = (hi - cpp) if cpp <= lo else (cpp - lo)
            if wdth <= cwidth:
                lo = min(lo, cpp)
                hi = max(hi, cpp)
                numpp += 1
                
        # 4. Check for Overlaps with existing clusters
        overlaps = False
        for k in range(len(sr_levels)):
            ex_hi = sr_levels[k]['hi']
            ex_lo = sr_levels[k]['lo']
            ex_str = sr_levels[k]['strength']
            
            # Overlap check
            if (ex_hi >= lo and ex_hi <= hi) or (ex_lo >= lo and ex_lo <= hi):
                overlaps = True
                # Replace if the new cluster has equal or greater strength
                if numpp >= ex_str:
                    sr_levels[k] = {'hi': hi, 'lo': lo, 'strength': numpp, 'mid': round((hi+lo)/2, 2)}
                break
                
        # 5. Add new non-overlapping cluster if it meets minimum strength
        if not overlaps:
            if numpp >= min_strength:
                sr_levels.append({'hi': hi, 'lo': lo, 'strength': numpp, 'mid': round((hi+lo)/2, 2)})
                
    # 6. Sort by strength descending and limit to `max_sr` zones
    sr_levels.sort(key=lambda x: x['strength'], reverse=True)
    return sr_levels[:max_sr]
