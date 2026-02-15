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
         
         if total_range > 0:
             wick_pct = upper_wick / total_range
             
             # Hard Rejection: Wick > 50% involved (Ugly Candle)
             if wick_pct > 0.50:
                 reasons.append(f"Huge Wick Rejection ({wick_pct:.0%} > 50%)")
             
             # Context Rejection: Wick > 35% AND High Volume (> 1.2x Avg) -> Selling Pressure
             elif wick_pct > 0.35:
                 current_vol = last_row.get('volume', 0)
                 avg_vol = vol_sma if vol_sma > 0 else 1
                 vol_ratio = current_vol / avg_vol
                 
                 if vol_ratio > 1.2:
                      reasons.append(f"Wick Rejection: Wick {wick_pct:.0%} + Volume {vol_ratio:.1f}x (Seller Pressure)")

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
    
    if current_ema and past_ema:
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
        
        return {
            "PDH": prev_day['high'],
            "PDL": prev_day['low'],
            "CDH": curr_day['high'],
            "CDL": curr_day['low']
        }
    except Exception as e:
        # Logging not available here
        return None
