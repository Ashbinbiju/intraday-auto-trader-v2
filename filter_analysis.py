"""
Filter Analysis: Which stock change% range produces the best backtest results?
Tests multiple stocks from different change brackets on 2026-04-24 data.
"""
import subprocess
import json
import os

# Stocks categorized by their approximate daily change% on April 24
# Data from intradayscreener.com sector pages
test_stocks = {
    "0.0-0.5%": [
        ("WELCORP", 0.28), ("GAIL", 0.39), ("PNB", 0.34), ("SUZLON", 0.34),
        ("KOTAKBANK", 0.12), ("HDFCBANK", 0.06)
    ],
    "0.5-1.0%": [
        ("MAHABANK", 0.76), ("SBIN", 0.63), ("AUBANK", 0.89),
        ("HINDALCO", 0.67), ("ATGL", 0.83), ("NLCINDIA", 0.74)
    ],
    "1.0-2.0%": [
        ("COALINDIA", 1.19), ("TATAPOWER", 1.09), ("AEGISLOG", 1.38),
        ("POWERINDIA", 1.51), ("ADANIGREEN", 1.78), ("SAIL", 1.14),
        ("CHOLAFIN", 1.5)
    ],
    "2.0-4.0%": [
        ("NMDC", 2.27), ("ADANIENSOL", 3.72)
    ]
}

results_by_bracket = {}

for bracket, stocks in test_stocks.items():
    bracket_results = {"wins": 0, "losses": 0, "no_signal": 0, "total_pnl": 0, "trades": []}
    
    for symbol, change_pct in stocks:
        try:
            result = subprocess.run(
                ["python", "backtest.py", "--symbol", symbol, "--from", "2026-04-24", "--to", "2026-04-24", "--source", "yf"],
                capture_output=True, text=True, timeout=30, cwd=r"e:\intraday-auto-trader-v2",
                encoding='utf-8', errors='replace'
            )
            
            if result.returncode != 0:
                print(f"  Warning: backtest for {symbol} exited with code {result.returncode}")
                bracket_results['no_signal'] += 1
                continue
            
            # Parse the JSON output file
            json_file = f"backtest_{symbol}_2026-04-24_to_2026-04-24.json"
            json_path = os.path.join(r"e:\intraday-auto-trader-v2", json_file)
            
            if os.path.exists(json_path):
                with open(json_path, 'r') as f:
                    trades = json.load(f)
                
                for trade in trades:
                    if trade['status'] == 'NO_SIGNAL':
                        bracket_results['no_signal'] += 1
                    else:
                        pnl = trade.get('pnl_pts', 0)
                        bracket_results['total_pnl'] += pnl
                        if pnl > 0:
                            bracket_results['wins'] += 1
                        elif pnl == 0:
                            pass  # Breakeven - don't count as win or loss
                        else:
                            bracket_results['losses'] += 1
                        bracket_results['trades'].append({
                            'symbol': symbol, 'change': change_pct,
                            'pnl': round(pnl, 2), 'status': trade['status']
                        })
                
                # Clean up JSON file
                os.remove(json_path)
            else:
                bracket_results['no_signal'] += 1
                
        except Exception as e:
            print(f"  Error testing {symbol}: {e}")
            bracket_results['no_signal'] += 1
    
    results_by_bracket[bracket] = bracket_results

# Print Analysis
print("\n" + "=" * 80)
print("  FILTER ANALYSIS REPORT - April 24, 2026")
print("=" * 80)

for bracket, data in results_by_bracket.items():
    total_trades = data['wins'] + data['losses']
    win_rate = (data['wins'] / total_trades * 100) if total_trades > 0 else 0
    
    print(f"\n  [{bracket}] Change Range")
    print(f"  Trades: {total_trades} ({data['wins']}W / {data['losses']}L) | No Signal: {data['no_signal']}")
    print(f"  Win Rate: {win_rate:.0f}% | Total P&L: {data['total_pnl']:+.2f} pts")
    
    if data['trades']:
        print(f"  Details:")
        for t in data['trades']:
            icon = "W" if t['pnl'] > 0 else "L"
            print(f"    [{icon}] {t['symbol']:12s} (chg: {t['change']:.2f}%) -> {t['status']:14s} P&L: {t['pnl']:+.2f}")

print("\n" + "=" * 80)
print("  RECOMMENDATION")
print("=" * 80)

# Find best bracket
if results_by_bracket:
    best = max(results_by_bracket.items(), key=lambda x: x[1]['total_pnl'])
    print(f"\n  Best Bracket: {best[0]} (P&L: {best[1]['total_pnl']:+.2f} pts)")
else:
    print("\n  No results to analyze.")

