
import logging
from dhan_api_helper import get_dhan_session, load_dhan_instrument_map, fetch_candle_data
from indicators import calculate_indicators, check_buy_condition, check_15m_bias
import pandas as pd
from datetime import datetime

# Setup simple logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def analyze_trade(symbol):
    print(f"--- Analyzing {symbol} ---")
    
    # 1. Login
    dhan = get_dhan_session()
    if not dhan:
        print("Login failed.")
        return

    # 2. Get Token
    token_map = load_dhan_instrument_map()
    # Handle suffix variations if needed, map usually has 'SYMBOL-EQ' or just 'SYMBOL'
    # Try exact match first, then with -EQ
    token = token_map.get(f"{symbol}-EQ") or token_map.get(symbol)
    
    if not token:
        print(f"Token not found for {symbol}")
        # Debug: print some keys
        # print(list(token_map.keys())[:10])
        return
    else:
        print(f"Token: {token}")

    # 3. Fetch Data (15M and 5M)
    print("Fetching 15M Data...")
    df_15m = fetch_candle_data(dhan, token, symbol, "FIFTEEN_MINUTE", days=3)
    
    print("Fetching 5M Data...")
    df_5m = fetch_candle_data(dhan, token, symbol, "FIVE_MINUTE", days=3)

    if df_15m is None or df_5m is None:
        print("Failed to fetch data.")
        return

    # 4. Calculate Indicators
    df_15m = calculate_indicators(df_15m)
    df_5m = calculate_indicators(df_5m)
    
    print(f"5M Data Count: {len(df_5m)}")
    print(f"5M Data Start: {df_5m['datetime'].min()}")
    print(f"5M Data End: {df_5m['datetime'].max()}")

    # 5. Analyze the last few candles (focusing on late session)

    # 5. Analyze the specific candle that would trigger a 15:13 signal (i.e. 15:10 candle)
    print("\n--- Specifc Analysis for 15:10 Candle ---")
    
    # Convert entire DF to IST for easier filtering
    # Assuming 'datetime' is naive UTC (from epoch)
    df_5m['datetime'] = df_5m['datetime'].dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
    df_15m['datetime'] = df_15m['datetime'].dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
    
    target_time_str = "15:10"
    # Find the row where time component matches 15:05 or 15:10?
    # Trade at 15:13 implied analysis of 15:10 closed candle? 
    # Or 15:05 closed candle? 
    # 5M candles: 15:00-15:05, 15:05-15:10, 15:10-15:15.
    # At 15:13, the last COMPLETE candle is 15:10. (Wait, 15:10 candle closes at 15:15?)
    # NO. 15:10 candle starts at 15:10 and closes at 15:15.
    # At 15:13, the 15:10 candle is FORMING (Live).
    # The last COMPLETED candle is 15:05 (15:05-15:10).
    # So we should check the 15:05 candle!
    
    # Target 15:00, 15:05, 15:10 (IST) for TODAY
    today = datetime.now().date()
    subset = df_5m[
        (df_5m['datetime'].dt.date == today) & 
        (df_5m['datetime'].dt.strftime('%H:%M') == '15:05')
    ]
    
    print(f"Found {len(subset)} candles matching target times for {today}.")
    
    results = []
    
    for i, row in subset.iterrows():
        time_str = row['datetime'].strftime("%Y-%m-%d %H:%M:%S")
        close = row['close']
        vwap = row.get('VWAP')
        ema = row.get('EMA_20')
        vol = row['volume']
        vol_sma = row.get('Volume_SMA_20')
        
        # 15M Bias Logic
        bias_15m = "N/A"
        # Approximate 15M candle (14:45 for 15:05/15:10 timestamps)
        latest_15m_idx = df_15m[df_15m['datetime'] <= row['datetime']].index[-1]
        bias_candle = df_15m[df_15m['datetime'].dt.strftime('%H:%M') == '14:45']
        
        if not bias_candle.empty:
            b_row = bias_candle.iloc[0]
            if b_row['close'] > b_row['VWAP'] and b_row['close'] > b_row['EMA_20']: bias_15m = "BULLISH"
            elif b_row['close'] < b_row['VWAP'] and b_row['close'] < b_row['EMA_20']: bias_15m = "BEARISH"
            else: bias_15m = "NEUTRAL"
            
        # Logic Check
        is_green = row['close'] > row['open']
        above_levels = close > vwap and close > ema
        vol_spike = vol > (vol_sma * 1.5) if vol_sma else False
        
        reasons = []
        if not is_green: reasons.append("Red Candle")
        if not above_levels: reasons.append("Below Levels")
        # if not vol_spike: reasons.append(f"Low Volume ({vol} < {int(vol_sma*1.5)})")
        if not vol_spike: reasons.append("Low Volume")
        if bias_15m != "BULLISH": reasons.append(f"Bias {bias_15m}")
        
        verdict = "VALID" if not reasons else f"INVALID: {', '.join(reasons)}"
        
        results.append({
            "time": time_str,
            "verdict": verdict,
            "price": close,
            "vol": vol,
            "vol_req": vol_sma * 1.5 if vol_sma else 0,
            "bias": bias_15m
        })
        
    import json
    print("JSON_RESULT:" + json.dumps(results))


if __name__ == "__main__":
    analyze_trade("GUJGASLTD")
