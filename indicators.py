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
    
    return df


def check_buy_condition(df, current_price=None):
    """
    Checks the Buy condition on the latest closed candle or live price.
    Condition: Price > VWAP AND Price > EMA 20
    """
    if df is None or df.empty:
        return False, "No Data"

    # Get latest completed candle (assuming the last row is the latest completed or current building candle)
    # Usually strictly wait for close. But for "Auto Buy", users often want "Current Live Price" > Indicator.
    # Since we fetch 15 min candles, the indicators are valid for the *previous* close or current-updating.
    # We will use the LATEST AVAILABLE row for indicators.
    
    last_row = df.iloc[-1]
    ema_20 = last_row['EMA_20']
    vwap = last_row['VWAP']
    
    # If current_price is not provided, use the close of the last candle
    price = current_price if current_price else last_row['close']
    
    if pd.isna(ema_20) or pd.isna(vwap):
        return False, "Not enough data for indicators"
    
    if price > vwap and price > ema_20:
        # Late Entry Protection (Guard)
        ema_dist = ((price - ema_20) / ema_20) * 100
        if ema_dist > 1.5:
             return False, f"Late Entry Guard: Price is {ema_dist:.2f}% > EMA20 (Max 1.5%)"

        return True, f"Price ({price}) > VWAP ({vwap:.2f}) & EMA20 ({ema_20:.2f})"
    
    # Analyze Failure Reason
    reasons = []
    if price <= vwap:
        diff = ((vwap - price) / price) * 100
        reasons.append(f"Price below VWAP (-{diff:.2f}%)")
    if price <= ema_20:
        diff = ((ema_20 - price) / price) * 100
        reasons.append(f"Price below EMA20 (-{diff:.2f}%)")
        
    return False, f"Skipped: {', '.join(reasons)}"
