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

    return df


def check_buy_condition(df, current_price=None):
    """
    Checks the Buy condition on the latest closed candle or live price.
    Condition: Price > VWAP AND Price > EMA 20 AND Green Candle AND Volume > 1.5x Avg
    """
    if df is None or df.empty:
        return False, "No Data"

    # Get latest completed candle (Avoid Repainting by using iloc[-2])
    # iloc[-1] is usually the forming candle in live data.
    if len(df) < 2:
        return False, "Not enough data"
        
    last_row = df.iloc[-2]
    
    # Extract Indicators
    ema_20 = last_row.get('EMA_20')
    vwap = last_row.get('VWAP')
    vol_sma = last_row.get('Volume_SMA_20')
    current_vol = last_row.get('volume')
    open_price = last_row.get('open')
    close_price = last_row.get('close')
    
    # If current_price is provided (live check), override close
    price = current_price if current_price else close_price
    
    if pd.isna(ema_20) or pd.isna(vwap) or pd.isna(vol_sma):
        return False, "Not enough data for indicators"
    
    reasons = []

    # 1. Trend Conditions
    if price <= vwap:
        reasons.append(f"Price below VWAP")
    if price <= ema_20:
        reasons.append(f"Price below EMA20")

    # 2. Candle Color (Green)
    if price <= open_price:
         reasons.append("Red Candle (Price <= Open)")

    # 3. Volume Confirmation (Volume Spike > 1.5x Average)
    # Note: Only check volume on the closed candle basis to avoid partial candle noise, 
    # unless we are sure current_vol is live and extrapolated. 
    # For safety, we use the candle's volume.
    if current_vol <= (vol_sma * 1.5):
        reasons.append(f"Low Volume ({current_vol} < 1.5x Avg {int(vol_sma)})")

    if not reasons:
        # Late Entry Protection (Guard)
        ema_dist = ((price - ema_20) / ema_20) * 100
        if ema_dist > 1.5:
             return False, f"Late Entry Guard: Price is {ema_dist:.2f}% > EMA20 (Max 1.5%)"

        return True, f"Strong Buy: Price > VWAP/EMA20 + Vol Spike ({int(current_vol)}) + Green Candle"
    
    return False, f"Skipped: {', '.join(reasons)}"
