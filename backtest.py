"""
backtest.py - Historical Backtester for Intraday Auto-Trader v2
================================================================
Reuses the EXACT same strategy logic as the live bot:
  - check_buy_condition (VWAP, EMA, Volume, Extension, Wick filters)
  - check_15m_bias (HTF trend confirmation)
  - get_dynamic_sr_levels (Auto-Pivot Resistance)
  - calculate_structure_based_sl / calculate_structure_based_tp
  - 3-Level Continuous Trailing Stop Loss (TSL)

Usage:
  python backtest.py --symbol IDFCFIRSTB --token 11184 --from 2026-02-10 --to 2026-02-21
  python backtest.py --symbol BAJFINANCE --token 1270 --from 2026-02-10 --to 2026-02-21
"""

import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# ─── Setup path so we can import project modules ─────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dhan_api_helper import get_dhan_session, data_limiter
from indicators import (
    calculate_indicators,
    check_buy_condition,
    check_15m_bias,
    get_dynamic_sr_levels,
    calculate_sr_levels,
)
from main import calculate_structure_based_sl, calculate_structure_based_tp
from dhanhq import dhanhq


# ─── Constants ────────────────────────────────────────────────────────────────
ENTRY_END_TIME   = "14:30"   # No new entries after this time
SQUARE_OFF_TIME  = "15:15"   # Force-close all open positions
EXTENSION_LIMIT  = 1.5       # Max % from EMA20 (same as live bot)
MIN_RR           = 1.5       # Minimum risk:reward to accept a trade


# ─── Data Fetching ────────────────────────────────────────────────────────────

def fetch_historical_candles(dhan, token: str, from_date: str, to_date: str, interval_min: int = 5) -> pd.DataFrame | None:
    """
    Fetch historical intraday candles from Dhan API using the native interval param.
    Supports interval_min: 1, 5, 15, 25, 60
    """
    try:
        data_limiter.wait()
        raw = dhan.intraday_minute_data(
            security_id=str(token),
            exchange_segment=dhanhq.NSE,
            instrument_type='EQUITY',
            from_date=from_date,
            to_date=to_date,
            interval=interval_min,  # Native: 1, 5, 15, 25, 60
        )

        if raw.get('status') != 'success' or not raw.get('data'):
            print(f"  [WARN] Dhan API returned no data for token {token}. Response: {raw.get('remarks', raw)}")
            return None

        r = raw['data']
        time_key = next((k for k in ['timestamp', 'start_Time', 'start_time', 'time'] if k in r), None)
        if not time_key:
            print(f"  ⚠️  Cannot find time key. Keys: {list(r.keys())}")
            return None

        df = pd.DataFrame({
            'datetime': pd.to_datetime(r[time_key], unit='s' if isinstance(r[time_key][0], (int, float)) else None),
            'open':   r['open'],
            'high':   r['high'],
            'low':    r['low'],
            'close':  r['close'],
            'volume': r['volume'],
        })

        # Dhan API returns timestamps in UTC. Convert to IST (UTC+5:30).
        df['datetime'] = df['datetime'] + pd.Timedelta(hours=5, minutes=30)

        df = df.sort_values('datetime').reset_index(drop=True)
        return df

    except Exception as e:
        print(f"  [ERR] Error fetching candles: {e}")
        return None



# ─── Simulation Engine ────────────────────────────────────────────────────────

def simulate_all(df_5m: pd.DataFrame, df_15m: pd.DataFrame) -> list:
    """
    Walk-forward bar-by-bar simulation over the entire historical dataset.
    Preserves multi-day history for accurate EMA and Pivot calculations.
    """
    WARMUP = 50  # More warmup candles needed for multi-day indicators
    position = None
    results = []

    # Map 15m data by date for quick access
    df_15m['date_str'] = pd.to_datetime(df_15m['datetime']).dt.date.astype(str)
    
    current_day = None
    daily_no_signal = True

    for i in range(WARMUP + 1, len(df_5m)):
        bar      = df_5m.iloc[i]
        bar_time = bar['datetime']
        bar_date = bar_time.date()
        bar_time_str = bar_time.strftime("%H:%M") if hasattr(bar_time, 'strftime') else str(bar_time)

        if current_day != bar_date:
            # End of previous day - record NO SIGNAL if nothing happened
            if current_day is not None and daily_no_signal:
                results.append({'date': str(current_day), 'status': 'NO_SIGNAL'})
            current_day = bar_date
            daily_no_signal = True

        # ── If position is open: manage it ──────────────────────────────────
        if position:
            current_price = bar['close']
            high_of_bar   = bar['high']
            low_of_bar    = bar['low']

            if high_of_bar > position['highest_ltp']:
                position['highest_ltp'] = high_of_bar

            # 1. Hard Stop Loss
            if low_of_bar <= position['sl']:
                position['exit_price']  = position['sl']
                position['exit_reason'] = 'STOP_LOSS'
                position['exit_time']   = bar_time_str
            # 2. Take Profit
            elif position['tp'] and high_of_bar >= position['tp']:
                position['exit_price']  = position['tp']
                position['exit_reason'] = 'TARGET_HIT'
                position['exit_time']   = bar_time_str
            # 4. Square-Off Time
            elif bar_time_str >= SQUARE_OFF_TIME:
                position['exit_price']  = current_price
                position['exit_reason'] = 'TIME_EXIT'
                position['exit_time']   = bar_time_str
            
            # If an exit occurred this bar, finalize position
            if 'exit_price' in position:
                pnl = position['exit_price'] - position['entry_price']
                results.append({
                    'date':        str(bar_date),
                    'status':      position['exit_reason'],
                    'entry_price': round(position['entry_price'], 2),
                    'exit_price':  round(position['exit_price'], 2),
                    'entry_time':  position['entry_time'],
                    'exit_time':   position['exit_time'],
                    'sl':          round(position['original_sl'], 2),
                    'tp':          round(position['tp'], 2) if position['tp'] else 0,
                    'tp_reason':   position['tp_reason'],
                    'rr_ratio':    round(position['rr_ratio'], 2),
                    'pnl_pts':     round(pnl, 2),
                })
                position = None
                continue

            # 3. Continuous Trailing Stop Loss
            risk_per_share = position['entry_price'] - position['original_sl']
            if risk_per_share > 0:
                max_profit = position['highest_ltp'] - position['entry_price']
                max_rr     = max_profit / risk_per_share
                current_level = position.get('tsl_level', 0)
                proposed_sl   = position['sl']
                new_level     = current_level

                if max_rr >= 1.0 and current_level < 1:
                    proposed_sl = position['entry_price'] * 1.001
                    new_level   = 1
                elif max_rr >= 2.0 and current_level < 2:
                    proposed_sl = position['entry_price'] + (1.0 * risk_per_share)
                    new_level   = 2
                elif max_rr >= 3.0 and current_level < 3:
                    proposed_sl = position['entry_price'] + (2.0 * risk_per_share)
                    new_level   = 3

                if proposed_sl > position['sl']:
                    position['sl']        = proposed_sl
                    position['tsl_level'] = new_level

            continue  # No exit this bar — keep holding

        # ── No position: look for entry signal ──────────────────────────────
        if bar_time_str >= ENTRY_END_TIME:
            continue

        # Use continuous history up to this bar (simulate live bot 5-day fetch)
        df_slice_5m = df_5m.iloc[:i].copy()
        
        # 15M history up to current date
        df_slice_15m = df_15m[df_15m['date_str'] <= str(bar_date)].copy()


        if len(df_slice_5m) < WARMUP + 1:
            continue

        # Calculate indicators
        df_ind = calculate_indicators(df_slice_5m)
        if df_ind is None or len(df_ind) < 2:
            continue

        df_15m_ind = calculate_indicators(df_slice_15m)

        # HTF bias
        bias, bias_msg = check_15m_bias(df_15m_ind)
        if bias != 'BULLISH':
            continue

        # 5M Buy signal
        signal, signal_msg = check_buy_condition(df_ind, extension_limit=EXTENSION_LIMIT)
        if not signal:
            continue

        # Entry price = close of the CONFIRMED candle (iloc[-2])
        confirmed = df_ind.iloc[-2]
        entry_price = confirmed['close']
        vwap        = confirmed['VWAP']
        ema20       = confirmed['EMA_20']

        # S/R Resistance Check (Rejection if < 0.25% away)
        static_res = []
        sr_levels = calculate_sr_levels(df_slice_15m)
        pdh = None
        cdh_val = None
        if sr_levels:
            pdh = sr_levels.get('PDH')
            cdh_val = sr_levels.get('CDH')
            if pdh and pdh > entry_price: static_res.append(pdh)
            if cdh_val and cdh_val > entry_price: static_res.append(cdh_val)

        dynamic_res = []
        dyn_levels = get_dynamic_sr_levels(df_ind)
        if dyn_levels:
            for lvl in dyn_levels:
                if lvl['lo'] > entry_price:
                    dynamic_res.append(lvl['lo'])
        
        all_res = static_res + dynamic_res
        nearest_res = min(all_res) if all_res else None

        if nearest_res:
            dist_pct = (nearest_res - entry_price) / entry_price * 100
            if dist_pct < 0.25:
                # Trade rejected: Too close to resistance
                continue

        # Calculate SL
        sl_price, sl_reason, sl_dist_pct = calculate_structure_based_sl(
            df_ind, entry_price, vwap, ema20
        )
        if sl_price is None:
            continue

        # Convert back remaining resistances for TP (dynamic_res needs 'hi' or 'mid' for TP targets via main.py)
        tp_dynamic_res = []
        if dyn_levels:
            for lvl in dyn_levels:
                hi = lvl.get('hi') or lvl.get('mid')
                if hi and hi > entry_price:
                    tp_dynamic_res.append(hi)
            tp_dynamic_res = [r for r in tp_dynamic_res if ((r - entry_price) / entry_price * 100) >= 0.6]

        if pdh and pdh <= entry_price:
            pdh = None


        # Calculate TP
        tp_price, tp_reason, rr_ratio = calculate_structure_based_tp(
            entry_price, sl_price, df_ind, pdh, dynamic_res
        )
        if tp_price is None:
            continue  # Trade rejected due to low R:R or no target

        # ── Open Position ────────────────────────────────────────────────────
        position = {
            'entry_price': entry_price,
            'entry_time':  bar_time_str,
            'sl':          sl_price,
            'original_sl': sl_price,
            'tp':          tp_price,
            'tp_reason':   tp_reason,
            'rr_ratio':    rr_ratio,
            'highest_ltp': entry_price,
            'tsl_level':   0,
            'sl_reason':   sl_reason,
        }

    # Market closed with no exit
    # Market data ended
    if position and 'exit_price' not in position:
        position['exit_price']  = df_5m.iloc[-1]['close']
        position['exit_reason'] = 'NO_EXIT_DATA'
        position['exit_time']   = 'EOD'

    if position:
        pnl = position['exit_price'] - position['entry_price']
        results.append({
            'date':        str(current_day),
            'status':      position['exit_reason'],
            'entry_price': round(position['entry_price'], 2),
            'exit_price':  round(position['exit_price'], 2),
            'entry_time':  position['entry_time'],
            'exit_time':   position['exit_time'],
            'sl':          round(position['original_sl'], 2),
            'tp':          round(position['tp'], 2) if position['tp'] else 0,
            'tp_reason':   position['tp_reason'],
            'rr_ratio':    round(position['rr_ratio'], 2),
            'pnl_pts':     round(pnl, 2),
        })
    elif daily_no_signal and current_day is not None:
        results.append({'date': str(current_day), 'status': 'NO_SIGNAL'})

    return results


# ─── Report Printer ───────────────────────────────────────────────────────────

def print_report(symbol: str, results: list):
    print("\n" + "═" * 80)
    print(f"  BACKTEST REPORT  —  {symbol}")
    print("═" * 80)
    print(f"  {'DATE':<12} {'ENTRY':>8} {'EXIT':>8} {'SL':>8} {'TP':>8} {'RR':>5}  {'RESULT':<14}  {'P&L PTS':>8}")
    print("─" * 80)

    total_pnl    = 0
    wins         = 0
    losses       = 0
    no_signal    = 0

    for r in results:
        if r['status'] == 'NO_SIGNAL':
            no_signal += 1
            print(f"  {r['date']:<12} {'—':>8} {'—':>8} {'—':>8} {'—':>8} {'—':>5}  {'NO SIGNAL':<14}  {'—':>8}")
            continue

        pnl   = r['pnl_pts']
        total_pnl += pnl
        if pnl > 0:
            wins += 1
            icon = '[WIN] '
        else:
            losses += 1
            icon = '[LOSS]'

        print(
            f"  {r['date']:<12} {r['entry_price']:>8.2f} {r['exit_price']:>8.2f} "
            f"{r['sl']:>8.2f} {r['tp']:>8.2f} {r['rr_ratio']:>5.2f}  "
            f"{icon} {r['status']:<12}  {pnl:>+8.2f}"
        )

    traded = wins + losses
    win_rate = (wins / traded * 100) if traded > 0 else 0

    print("─" * 80)
    print(f"  Total Trades : {traded} ({wins}W / {losses}L) | No-Signal Days: {no_signal}")
    print(f"  Win Rate     : {win_rate:.1f}%")
    print(f"  Total P&L    : {total_pnl:+.2f} pts")
    print("═" * 80 + "\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest the Intraday Auto-Trader strategy on historical data.")
    parser.add_argument('--symbol', required=True, help='NSE Symbol (e.g. IDFCFIRSTB)')
    parser.add_argument('--token',  required=True, help='Dhan Security ID / Token (e.g. 11184)')
    parser.add_argument('--from',   dest='from_date', required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--to',     dest='to_date',   required=True, help='End date YYYY-MM-DD')
    args = parser.parse_args()

    print("\n[+] Connecting to Dhan API...")
    dhan = get_dhan_session()

    print(f"[+] Fetching 5-min candles for {args.symbol} ({args.token}) from {args.from_date} to {args.to_date}...")
    df_5m = fetch_historical_candles(dhan, args.token, args.from_date, args.to_date, interval_min=5)
    if df_5m is None or df_5m.empty:
        print("[ERR] No 5-min data returned. Exiting.")
        return

    print("[+] Fetching 15-min candles...")
    df_15m = fetch_historical_candles(dhan, args.token, args.from_date, args.to_date, interval_min=15)
    if df_15m is None or df_15m.empty:
        print("[WARN] No 15-min data. HTF bias will be NEUTRAL for all days.")
        df_15m = pd.DataFrame()

    # Run continuous simulation
    print(f"\n[+] Running continuous walk-forward simulation with {len(df_5m)} total candles...\n")
    results = simulate_all(df_5m, df_15m)

    for result in results:
        status = result['status']
        if status == 'NO_SIGNAL':
            print(f"  >> {result['date']} ... No Signal")
        else:
            pnl = result['pnl_pts']
            print(f"  >> {result['date']} ... Entry {result['entry_time']} @ {result['entry_price']} -> {status} @ {result['exit_price']}  [{pnl:+.2f} pts]")

    print_report(args.symbol, results)

    # Also save to JSON for easy review
    import json
    out_file = f"backtest_{args.symbol}_{args.from_date}_to_{args.to_date}.json"
    with open(out_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[+] Full results saved to: {out_file}")


if __name__ == '__main__':
    main()
