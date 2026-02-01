def check_sentiment(scenario_name, open_price, high, low, ltp):
    print(f"\n--- Scenario: {scenario_name} ---")
    print(f"Data: Open={open_price}, High={high}, Low={low}, LTP={ltp}")
    
    # 1. Old Logic (LTP > Open)
    old_bullish = ltp > open_price
    print(f"Old Logic (LTP > Open): {'✅ Bullish' if old_bullish else '❌ Bearish'}")
    
    # 2. New Sentinel Logic
    range_denominator = high - low
    if range_denominator == 0:
        print("Range is 0 (Dead Session)")
        return

    range_pos = (ltp - low) / range_denominator
    print(f"Range Position: {range_pos:.2f} ({(ltp - low):.2f} / {range_denominator:.2f})")
    
    if range_pos > 0.55:
        print("✅ New Logic: BULLISH (Extension: 3.0%)")
    else:
        print("❌ New Logic: WEAK (Extension: 1.5%)")

# Test Cases
check_sentiment("Strong Bullish Day", 21500, 21700, 21450, 21680)
# High=21700, Low=21450. Range=250. LTP=21680. Pos = (21680-21450)/250 = 230/250 = 0.92

check_sentiment("Gap Up & Fade (The Trap)", 21600, 21650, 21400, 21550)
# Open=21600 (Gap Up). High=21650. Low=21400. LTP=21550 (+0.7% maybe?).
# Pos = (21550-21400)/250 = 150/250 = 0.60
# Wait, 150/250 = 0.6. That is > 0.55.
# Let's adjust Fade to be weaker.
check_sentiment("gap Up & Fade (Weak)", 21600, 21650, 21400, 21480)
# Pos = (21480-21400)/250 = 80/250 = 0.32 (WEAK)

check_sentiment("Choppy / Flat", 21500, 21550, 21450, 21500)
# Pos = 0.5. (WEAK)
