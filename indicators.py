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


def check_buy_condition(df, current_price=None, extension_limit=1.5):
    """
    Checks the Buy condition on the latest closed candle or live price.
    Condition: Price > VWAP AND Price > EMA 20 AND Green Candle AND Volume > 1.5x Avg
    extension_limit: Max allowed % distance from EMA 20 (dynamic).
    """
    if df is None or df.empty:
        return False, "No Data"

    # Get latest completed candle (Avoid Repainting by using iloc[-2])
    # iloc[-1] is usually the forming candle in live data.
    if len(df) < 2:
        return False, "Not enough data"
        
    last_row = df.iloc[-2]
    
    # Extract Indicators (Strictly from Confirmed Candle)
    ema_20 = last_row.get('EMA_20')
    vwap = last_row.get('VWAP')
    vol_sma = last_row.get('Volume_SMA_20')
    closed_vol = last_row.get('volume') # From iloc[-2] (Completed Candle)
    open_price = last_row.get('open')
    close_price = last_row.get('close')
    datetime_str = str(last_row.get('datetime', 'Unknown'))
    
    # User Request: Price checks must match the candle exactly.
    # We IGNORE current_price for the Logic Check.
    price = close_price 
    
    # Debug/Sanity Check for User
    # logger.info(f"Checking Signal on Candle: {datetime_str} | Close: {price} | EMA: {ema_20} | VWAP: {vwap}")
    
    if pd.isna(ema_20) or pd.isna(vwap) or pd.isna(vol_sma):
        return False, "Not enough data for indicators"
    
    reasons = []

    # 1. Trend Conditions
    if price <= vwap:
        reasons.append(f"Price below VWAP")
    if price <= ema_20:
        reasons.append(f"Price below EMA20")

    # 1.1 Extension Filter (Don't chase if too far from EMA20)
    if ema_20 > 0:
        extension_pct = (price - ema_20) / ema_20 * 100
        if extension_pct > extension_limit:
            reasons.append(f"Overextended ({extension_pct:.2f}% > Limit {extension_limit}%)")

    # 2. Candle Color (Green)
    if price <= open_price:
         reasons.append("Red Candle (Price <= Open)")
    else:
         # 2.1 Wick Rejection Filter (Only on Green Candles)
         # Reject if Upper Wick > 40% of Total Range (Shooting Star / Rejection)
         # Refinement: Consider Volume Context
         high = last_row['high']
         low = last_row['low']
         upper_wick = high - close_price # For Green, Close is Max (safe)
         total_range = high - low
         
         if total_range == 0:
             reasons.append("Flat Candle (High = Low)")
         else:
             wick_pct = upper_wick / total_range
             candle_range_pct = (total_range / last_row['open']) * 100
             
             # Skip Wick Filter if candle is tiny (< 0.15% - Noise)
             if candle_range_pct >= 0.15:
                 # Pre-calculate Vol Ratio for Context
                 current_vol = last_row.get('volume', 0)
                 avg_vol = vol_sma if vol_sma > 0 else 1
                 vol_ratio = current_vol / avg_vol
                 
                 # Hard Rejection: Wick > 50% involved (Ugly Candle)
                 if wick_pct > 0.50:
                     reasons.append(f"Huge Wick Rejection ({wick_pct:.0%} > 50%) | Candle Size: {candle_range_pct:.2f}% | Vol: {vol_ratio:.1f}x")
                 
                 # Context Rejection: Wick > 35% AND High Volume (> 1.2x Avg) -> Selling Pressure
                 elif wick_pct > 0.35:
                     if vol_ratio > 1.2:
                          reasons.append(f"Wick Rejection: Wick {wick_pct:.0%} | Vol {vol_ratio:.1f}x | Candle Size {candle_range_pct:.2f}% (Seller Pressure)")

    # 3. Volume Confirmation (Adaptive Mechanism)
    # If in Trend Mode (ExtLimit >= 2.0), relax Vol to 1.2x.
    # Otherwise (Safety Mode), keep strict 1.5x.
    vol_multiplier = 1.2 if extension_limit >= 1.9 else 1.5
    
    if closed_vol < (vol_sma * vol_multiplier):
        reasons.append(f"Low Volume ({closed_vol} < {vol_multiplier}x Avg {int(vol_sma)})")

    # 4. Volatility Guard (Huge Candle Protection)
    # Reject if candle range is too big (Slippage/Exhaustion risk)
    # Safety Mode: Max 1.0% | Trend Mode: Max 1.5%
    max_candle_range = 1.5 if extension_limit >= 1.9 else 1.0
    
    # Use pre-calculated candle_range_pct if available, else calc
    if 'candle_range_pct' not in locals():
        candle_range_pct = ((last_row['high'] - last_row['low']) / last_row['open']) * 100
        
    if candle_range_pct > max_candle_range:
        reasons.append(f"Huge Candle ({candle_range_pct:.2f}% > Limit {max_candle_range}%)")

    if not reasons:
        # Late Entry Protection (Guard)
        ema_dist = ((price - ema_20) / ema_20) * 100
        if ema_dist > extension_limit:
             return False, f"Late Entry Guard: Price is {ema_dist:.2f}% > EMA20 (Max {extension_limit}%)"

        return True, f"Strong Buy: Price > VWAP/EMA20 + Vol Spike ({int(closed_vol)}) + Green Candle"
    
    return False, f"Skipped: {', '.join(reasons)}"


def check_15m_bias(df):
    """Checks 15-minute timeframe for trend bias/direction."""
    import pandas as pd
    if df is None or df.empty or len(df) < 5:
        return 'NEUTRAL', "Insufficient data for 15M bias"
    latest = df.iloc[-2]
    price = latest['close']
    vwap = latest.get('VWAP')
    ema_20 = latest.get('EMA_20')
    if pd.isna(vwap) or pd.isna(ema_20):
        return 'NEUTRAL', "Missing VWAP/EMA20 on 15M"
    
    # Explicit check for 0.0 which could be valid in some data feeds but invalid for indicators
    if vwap == 0 or ema_20 == 0:
        return 'NEUTRAL', "Zero value for VWAP/EMA20 on 15M"
        
    if price > vwap and price > ema_20:
        return 'BULLISH', f"15M: Price > VWAP ({vwap:.2f}) + EMA20"
    if price < vwap and price < ema_20:
        return 'BEARISH', f"15M: Price < VWAP ({vwap:.2f}) + below EMA20"
    return 'NEUTRAL', f"15M: Choppy (Price near VWAP/EMA20)"

def check_chop_filter(df):
    """
    Filters out stocks that are chopping sideways or have weak trends.
    Returns: (is_clean_trend, reason)
    """
    if df is None or len(df) < 10:
        return True, "Insufficient Data" # Default to True (allow) if data scarce
    
    # 1. VWAP Chop Check (Zig-Zag around VWAP)
    # Count how many times price crossed VWAP in last 10 candles
    recent = df.iloc[-10:]
    crosses = 0
    was_above = None
    
    for i, row in recent.iterrows():
        close = row['close']
        vwap = row.get('VWAP')
        # FIX: Handle 0.0 correctly (pd.isna allows 0, but rejects NaN/None)
        if pd.isna(vwap): continue
        
        is_above = close >= vwap
        if was_above is not None and is_above != was_above:
            crosses += 1
        was_above = is_above
        
    if crosses >= 4:
        # Too many crosses = CHOP
        return False, f"Choppy Action ({crosses} VWAP crosses in 10 candles)"

    # 2. EMA Slope Check (Trend Strength)
    # Compare EMA20 now vs 5 candles ago
    # FIX: Use completed candle (iloc[-2]) and 5 bars prior (iloc[-7]) 
    current_ema = df.iloc[-2].get('EMA_20')
    past_ema = df.iloc[-7].get('EMA_20') 
    
    if pd.notna(current_ema) and pd.notna(past_ema) and past_ema != 0:
        # FIX: Remove abs() - Long-only strategy needs POSITIVE slope
        slope_pct = ((current_ema - past_ema) / past_ema) * 100
        
        # If slope is negative or very flat (< 0.05% over 25 mins), it's weak
        if slope_pct < 0.05:
             return False, f"Weak/Negative Trend (EMA Slope {slope_pct:.3f}% < 0.05%)"

    return True, "Trend Clean"

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
