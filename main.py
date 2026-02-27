import logging
import time
import sys
import asyncio
import pandas as pd
import threading
from scraper import fetch_top_performing_sectors, fetch_stocks_in_sector, fetch_market_indices
from dhan_api_helper import get_dhan_session, load_dhan_instrument_map, fetch_candle_data, fetch_ltp, fetch_net_positions, place_order_api, fetch_holdings, verify_order_status, fetch_market_feed_bulk
from indicators import calculate_indicators, check_buy_condition
from utils import is_market_open, get_ist_now
from config import config_manager
from state_manager import load_state, save_state, start_auto_save, state_lock
from database import log_trade_to_db
from async_scanner import AsyncScanner
from telegram_helper import send_telegram_message

# Configure Logging
import datetime

def ist_converter(*args):
    utc_dt = datetime.datetime.now(datetime.timezone.utc)
    ist_dt = utc_dt + datetime.timedelta(hours=5, minutes=30)
    return ist_dt.timetuple()

class LogBufferHandler(logging.Handler):
    def emit(self_instance, record):
        try:
            log_entry = self_instance.format(record)
            # Append to global shared buffer
            if "BOT_STATE" in globals():
                if "logs" not in BOT_STATE:
                    BOT_STATE["logs"] = []
                BOT_STATE["logs"].append(log_entry)
                
                # Keep only last 500 logs (Increased for better debugging)
                if len(BOT_STATE["logs"]) > 500:
                    BOT_STATE["logs"] = BOT_STATE["logs"][-500:]
        except Exception:
            self_instance.handleError(record)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
formatter.converter = ist_converter

# Stream Handler (Stdout)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)

# Remove existing handlers to avoid duplicates
if root_logger.hasHandlers():
    root_logger.handlers.clear()

root_logger.addHandler(stream_handler)

# File Handler
file_handler = logging.FileHandler("trading_bot.log")
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

# UI Buffer Handler
buffer_handler = LogBufferHandler()
buffer_handler.setFormatter(formatter)
root_logger.addHandler(buffer_handler)

# Suppress noisy HTTP logs from Supabase client
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("MainBot")

# --- GLOBAL STATE INITIALIZATION ---
# Load state from disk or use default
BOT_STATE = load_state()

# Start background auto-save (every 60s to reduce log spam)
start_auto_save(BOT_STATE, interval=60)
# -----------------------------------

# === ORDER IDEMPOTENCY HELPERS ===
def generate_correlation_id(symbol, action):
    """
    Generates unique correlation ID for order tracking.
    Format: SYMBOL_YYYYMMDD_HHMMSS_mmm_ACTION
    Includes milliseconds to prevent same-second collisions.
    """
    now = get_ist_now()
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    milliseconds = int(now.microsecond / 1000)  # Convert to milliseconds
    return f"{symbol}_{timestamp}_{milliseconds:03d}_{action}"

def is_duplicate_order(correlation_id):
    """
    Checks if order with this correlation_id is already pending.
    Thread-safe check.
    """
    with state_lock:
        return correlation_id in BOT_STATE.get('pending_orders', {})

def is_order_inflight(symbol):
    """
    Checks if ANY order is currently pending execution for this symbol.
    Prevents the fast loop from double-firing on same setup.
    """
    with state_lock:
        pending = BOT_STATE.get('pending_orders', {})
        for cid, data in pending.items():
            if data.get('symbol') == symbol:
                return True
        return False

def register_pending_order(correlation_id, order_data):
    """
    Registers order as pending to prevent duplicates.
    Thread-safe registration.
    """
    with state_lock:
        if 'pending_orders' not in BOT_STATE:
            BOT_STATE['pending_orders'] = {}
        BOT_STATE['pending_orders'][correlation_id] = {
            'timestamp': time.time(),
            'symbol': order_data.get('symbol'),
            'action': order_data.get('action')
        }

def clear_pending_order(correlation_id):
    """
    Removes order from pending list after completion.
    Thread-safe removal.
    """
    with state_lock:
        if 'pending_orders' in BOT_STATE:
            BOT_STATE['pending_orders'].pop(correlation_id, None)

def check_and_register_pending_order(correlation_id, order_data):
    """
    Atomically checks if order is duplicate and registers it.
    Returns True if registered (new), False if duplicate.
    Prevents TOCTOU race conditions.
    """
    with state_lock:
        if 'pending_orders' not in BOT_STATE:
            BOT_STATE['pending_orders'] = {}
            
        if correlation_id in BOT_STATE['pending_orders']:
            return False 
            
        BOT_STATE['pending_orders'][correlation_id] = {
            'timestamp': time.time(),
            'symbol': order_data.get('symbol'),
            'action': order_data.get('action'),
            'order_id': None 
        }
        return True

def cleanup_pending_orders(dhan):
    """
    Periodic cleanup: removes orders in final states from pending list.
    Prevents memory bloat from stale pending orders and zombie locks.
    Thread-safe cleanup.
    """
    try:
        # Get snapshot of pending orders with lock
        with state_lock:
            pending = dict(BOT_STATE.get('pending_orders', {}))
        
        if not pending:
            return
        
        from dhan_api_helper import get_order_status
        
        current_time = time.time()
        for correlation_id, data in pending.items():
            order_id = data.get('order_id')
            age_seconds = current_time - data.get('timestamp', current_time)
            
            # Watchdog: If order lock is older than 90 seconds
            if age_seconds > 90:
                symbol = data.get('symbol', 'UNKNOWN')
                logger.warning(f"🚨 Watchdog: Zombie lock detected for {symbol} (Age: {int(age_seconds)}s). Re-querying Broker...")
                
                if order_id:
                    try:
                        status = get_order_status(dhan, order_id)
                        
                        if status in ["FILLED", "TRADED"]:
                            logger.info(f"✅ Watchdog: Order {order_id} was successfully filled. Lock can be natively dropped if positions reconcile.")
                            clear_pending_order(correlation_id)
                        elif status in ["REJECTED", "CANCELLED", "EXPIRED"]:
                            logger.info(f"❌ Watchdog: Order {order_id} failed ({status}). Unlocking {symbol}.")
                            clear_pending_order(correlation_id)
                        else:
                            # Might still be OPEN/PENDING at broker, leave lock alone but log
                            logger.info(f"⏳ Watchdog: Order {order_id} still pending at broker ({status}). Leaving lock.")
                    except Exception as e:
                        logger.error(f"Watchdog: Broker query failed for zombie order {order_id}: {e}")
                        # Keep it locked if we can't verify, or maybe force clear if extremely old?
                        if age_seconds > 600:
                             logger.critical(f"👽 Watchdog: Order {order_id} extremely old (>10m) and broker unresponsive. Force clearing lock.")
                             clear_pending_order(correlation_id)
                else:
                    # No order_id exists, meaning place_buy_order completely crashed before assigning one.
                    # It's a true zombie lock. We MUST unlock the symbol.
                    logger.critical(f"🧟 Watchdog: Zombie lock {correlation_id} for {symbol} has no Order ID! Force unlocking.")
                    clear_pending_order(correlation_id)
                    
    except Exception as e:
        logger.error(f"Pending order cleanup error: {e}")
# ==================================

def place_buy_order(dhan, symbol, token, qty, correlation_id=None):
    """
    Places a Buy Order.
    """
    dry_run = config_manager.get("general", "dry_run")
    if dry_run:
        logger.info(f"[DRY RUN] Simulated BUY Order Placed for {symbol} | Qty: {qty}")
        return True

    try:
        # Idempotency Check (Prevent duplicate orders)
        # Assuming correlation_id is provided by caller
        if correlation_id:
            order_data = {
                "symbol": symbol,
                "token": token,
                "qty": qty,
                "type": "BUY"
            }
            if not check_and_register_pending_order(correlation_id, order_data):
                logger.warning(f"Prevented Duplicate BUY Order: {correlation_id}")
                return None
        
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": symbol, # Fixed: Removed -EQ
            "symboltoken": token,
            "transactiontype": "BUY",
            "exchange": "NSE",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "quantity": qty
        }
        # Use helper place_order_api
        from dhan_api_helper import place_order_api
        orderId = place_order_api(dhan, orderparams)
        logger.info(f"Order Placed for {symbol} | Order ID: {orderId} | cID: {correlation_id}")
        
        # Store order_id with correlation_id for later cleanup (thread-safe)
        with state_lock:
            if correlation_id in BOT_STATE.get('pending_orders', {}):
                BOT_STATE['pending_orders'][correlation_id]['order_id'] = orderId
        
        send_telegram_message(f"🔵 **BUY ORDER PLACED**\nSymbol: {symbol}\nQty: {qty}")
        
        return orderId
    except Exception as e:
        logger.error(f"Order Placement Failed for {symbol}: {e} | cID: {correlation_id}")
        # Lock is cleared by the calling loop on failure if it returns None
        return None

# Shared State for API
DHAN_API_SESSION = None
TOKEN_MAP = {}



def place_sell_order(dhan, symbol, token, qty, reason="EXIT", correlation_id=None):
    """
    Places a Sell Order to exit a position with idempotency support.
    """
    # Generate correlation_id if not provided
    if not correlation_id:
        correlation_id = generate_correlation_id(symbol, reason)
    
    # Atomic Check & Register (Prevents Race Conditions)
    if not check_and_register_pending_order(correlation_id, {'symbol': symbol, 'action': reason}):
        logger.warning(f"⚠️ Duplicate SELL order prevented: {correlation_id}")
        return None
    
    dry_run = config_manager.get("general", "dry_run")
    if dry_run:
        logger.info(f"[DRY RUN] Simulated SELL for {symbol} | Reason: {reason} | Qty: {qty} | cID: {correlation_id}")
        clear_pending_order(correlation_id)
        return True

    try:
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": symbol, # Fixed: Removed -EQ
            "symboltoken": token,
            "transactiontype": "SELL",
            "exchange": "NSE",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "quantity": qty
        }
        # Use helper place_order_api
        from dhan_api_helper import place_order_api
        orderId = place_order_api(dhan, orderparams)
        logger.info(f"SELL Order Placed for {symbol} ({reason}) | Order ID: {orderId} | cID: {correlation_id}")
        
        # Store order_id with correlation_id for later cleanup (thread-safe)
        with state_lock:
            if correlation_id in BOT_STATE.get('pending_orders', {}):
                BOT_STATE['pending_orders'][correlation_id]['order_id'] = orderId
        
        return orderId
    except Exception as e:
        logger.error(f"SELL Order Failed for {symbol}: {e} | cID: {correlation_id}")
        # Only clear on true failure (order not placed at all)
        clear_pending_order(correlation_id)
        return None

def place_sell_order_with_retry(dhan, symbol, token, qty, reason, max_retries=3):
    """
    Places exit order with retry logic.
    CRITICAL: Places order ONCE, retries VERIFICATION to prevent duplicate sells.
    """
    # STEP 1: Place exit order ONCE
    logger.info(f"Placing exit order for {symbol} ({reason})")
    order_id = place_sell_order(dhan, symbol, token, qty, reason)
    
    if not order_id:
        logger.critical(f"🚨 Exit order placement FAILED for {symbol} ({reason})")
        return None, False, 0.0
    
    # STEP 2: Retry VERIFICATION (not placement)
    for attempt in range(1, max_retries + 1):
        logger.info(f"Verification attempt {attempt}/{max_retries} for {symbol} (Order: {order_id})")
        
        time.sleep(0.5)  # Wait for broker processing
        is_success, status, avg_price = verify_order_status(dhan, order_id)
        
        if is_success:
            logger.info(f"✅ Exit confirmed: {symbol} ({reason}) | Order: {order_id}")
            return order_id, True, avg_price
        else:
            logger.warning(f"⚠️ Verification attempt {attempt} status: {status}")
        
        if attempt < max_retries:
            time.sleep(0.5 * attempt)  # Exponential backoff: 0.5s, 1s
    
    # All verification attempts exhausted - check positions as last resort
    logger.warning(f"🔍 Verification timeout for {symbol}. Checking broker positions...")
    from dhan_api_helper import fetch_net_positions
    live_positions = fetch_net_positions(dhan)
    
    if live_positions:
        # Check if position is closed (order likely filled)
        symbol_found = any(
            pos.get("tradingsymbol", "").replace("-EQ", "") == symbol and int(pos.get("netqty", 0)) == 0
            for pos in live_positions
        )
        if symbol_found:
            logger.info(f"✅ Position confirmed closed via broker check: {symbol}")
            return order_id, True, 0.0 # Price unknown via this method, fallback to LTP
    
    logger.critical(f"🚨 Exit verification FAILED for {symbol} ({reason}) | Order: {order_id}")
    return order_id, False, 0.0  # Return order_id anyway (order was placed, just couldn't verify)

def get_account_balance(dhan, dry_run):
    """
    Fetches account balance for position sizing.
    For paper trading, uses configured virtual balance.
    For live trading, fetches from Angel One API.
    """
    if dry_run:
        balance = config_manager.get("position_sizing", "paper_trading_balance") or 100000
        logger.info(f"📊 [PAPER TRADING] Using virtual balance: ₹{balance:,.0f}")
        return float(balance)
    
    try:
        # Dhan Logic
        if hasattr(dhan, 'get_fund_limits'):
             fund_resp = dhan.get_fund_limits()
             # Dhan response: {'status': 'success', 'data': {'availabelBalance': 1000.0, ...}} or list?
             # Check docs or structure.
             # Usually: {'status': 'success', 'data': {'availabelBalance': 0.0, 'openingBalance': 0.0}}
             if fund_resp['status'] == 'success':
                 # Dhan key might be 'availabelBalance' (typo in some versions) or 'availableBalance'
                 # Let's check keys safely
                 data = fund_resp['data']
                 available_balance = data.get('availableBalance') or data.get('availabelBalance') or 0
                 logger.info(f"📊 [LIVE] Account balance fetched: ₹{float(available_balance):,.0f}")
                 return float(available_balance)
        
        # Fallback/Legacy (Angel)
        elif hasattr(dhan, 'rmsLimit'):
            rmsLimit = dhan.rmsLimit()
            if rmsLimit and 'data' in rmsLimit:
                available_balance = rmsLimit['data'].get('availablecash', 0)
                logger.info(f"📊 [LIVE] Account balance fetched: ₹{float(available_balance):,.0f}")
                return float(available_balance)
                
        logger.warning("Unable to fetch balance (Unknown API), using fallback: ₹100,000")
        return 100000.0
    except Exception as e:
        logger.error(f"Balance fetch failed: {e}, using fallback: ₹100,000")
        return 100000.0

def floor_to_lot_size(qty, symbol):
    """
    Rounds down quantity to valid lot size.
    TODO: Add lot size mapping for F&O stocks if needed.
    For now, equity trades allow any quantity.
    """
    # For equity intraday, lot size = 1 (no restrictions)
    # If you trade F&O later, add lot size mapping here
    return int(qty) # Do NOT force max(1, qty) as it overrides risk limits!


def get_leverage():
    """
    Centralized helper to get leverage from config.
    Defaults to 1.0 if None or <= 0 (prevents ZeroDivisionError and no-trade scenarios).
    """
    leverage_raw = config_manager.get("position_sizing", "leverage_equity")
    return leverage_raw if leverage_raw and leverage_raw > 0 else 1.0


def calculate_position_size(entry_price, sl_price, balance, risk_pct, max_position_pct, min_sl_pct, symbol):
    """
    Calculates dynamic position size with all safety checks.
    
    🔴 Critical Safety Checks:
    1. Zero SL distance protection
    2. Minimum SL distance enforcement (0.6%)
    3. Maximum position size limit (20%)
    4. Lot size rounding
    5. Comprehensive logging
    
    Args:
        entry_price: Entry price for the stock
        sl_price: Stop loss price
        balance: Account balance
        risk_pct: Risk per trade as % of balance (e.g., 1.0 for 1%)
        max_position_pct: Max position size as % of balance (e.g., 20.0)
        min_sl_pct: Minimum SL distance % (e.g., 0.6)
        symbol: Stock symbol for logging
    
    Returns:
        int: Quantity to buy (0 if invalid)
    """
    # 🔴 FIX 1: Zero SL distance protection & Direction Check
    # For BUY trades, SL *must* be below Entry.
    sl_distance = entry_price - sl_price
    
    if sl_distance <= 0:
        logger.warning(f"❌ {symbol}: Invalid SL (SL {sl_price} >= Entry {entry_price}), skipping trade")
        return 0
    
    # 🟢 FIX 4: Minimum SL distance enforcement
    sl_distance_pct = (sl_distance / entry_price) * 100
    if sl_distance_pct < min_sl_pct:
        logger.warning(
            f"❌ {symbol}: SL too tight ({sl_distance_pct:.2f}% < {min_sl_pct}%), "
            f"skipping trade to prevent sizing explosion"
        )
        return 0
    
    # Calculate risk amount
    risk_amount = balance * (risk_pct / 100)
    
    # Position size formula: Risk Amount / SL Distance
    qty = int(risk_amount / sl_distance)
    
    # Enforce maximum position size (prevent overexposure)
    # FIX: Ensure max_position_pct is strictly capped at 50.0 (Testing Mode)
    safe_max_pos_pct = min(float(max_position_pct), 50.0) 
    
    # === LEVERAGE UPDATE ===
    # Fetch leverage from config (default 1 if not set)
    leverage = get_leverage()
    
    # DEBUG: Log what we actually got from config
    logger.info(f"🔍 DEBUG Leverage: final={leverage}")
    
    # Calculate Buying Power = Cash * Leverage
    # Max Amount per Trade = Buying Power * (max_pos_pct / 100)
    # Max Qty = Max Amount / Entry Price
    max_amount = (balance * leverage) * (safe_max_pos_pct / 100)
    max_qty = int(max_amount / entry_price)
    
    qty = min(qty, max_qty)
    
    logger.info(f"Size Check: {symbol} | Bal={balance} | Lev={leverage}x | MaxAmt=₹{max_amount:.0f} | RiskQty={int(risk_amount/sl_distance)} | LimitQty={max_qty} -> Final={qty}")
    
    # 🟠 FIX 2: Lot size rounding
    qty = floor_to_lot_size(qty, symbol)
    
    # Ensure at least 1 share (if we got this far)
    if qty <= 0:
        logger.warning(f"❌ {symbol}: Position Sizing Failed. Qty={qty} (Max Qty={max_qty} due to Funds/Risk). Skipping.")
        return 0
    
    # Calculate actual exposure and risk
    exposure = qty * entry_price
    actual_risk = qty * sl_distance
    exposure_pct = (exposure / balance) * 100
    actual_risk_pct = (actual_risk / balance) * 100
    
    # Calculate Margin Used (Actual cash blocked)
    margin_used = exposure / leverage
    buying_power = balance * leverage
    
    # 4️⃣ FIX 5: Comprehensive logging
    logger.info(
        f"📊 Position Sizing | {symbol} | "
        f"Bal=₹{balance:,.0f} | Lev={leverage}x (BP=₹{buying_power:,.0f}) | "
        f"Risk={risk_pct}% (₹{risk_amount:,.0f}) | "
        f"SL={sl_distance:.2f} ({sl_distance_pct:.2f}%) | "
        f"Qty={qty} | Exposure=₹{exposure:,.0f} | "
        f"Margin Used=₹{margin_used:,.0f} | "
        f"Actual Risk=₹{actual_risk:,.0f} ({actual_risk_pct:.2f}%)"
    )
    
    return qty

def calculate_structure_based_sl(df, entry_price, vwap, ema20):
    """
    Calculate Stop-Loss based on nearest market structure.
    Uses priority weighting: Swing Low > VWAP > EMA20.
    
    Returns: (sl_price, sl_reason, sl_distance_pct) or (None, reason, 0)
    """
    buffer_pct = config_manager.get("structure_risk", "sl_buffer_pct") or 0.002  # 0.2%
    min_sl_distance = config_manager.get("structure_risk", "min_sl_distance_pct") or 0.8
    max_sl_distance = config_manager.get("structure_risk", "max_sl_distance_pct") or 2.0
    
    # Priority weighting (higher = stronger structure)
    priority = {
        "Swing Low": 3,  # Strongest - actual market structure
        "VWAP": 2,       # Dynamic support
        "EMA20": 1       # Trend indicator
    }
    
    # Option 1: Swing Low (last 10 candles)
    recent_candles = df.iloc[-10:]
    swing_low = recent_candles['low'].min()
    swing_low_sl = swing_low * (1 - buffer_pct)
    
    # Option 2: VWAP-based
    vwap_sl = vwap * (1 - buffer_pct)
    
    # Option 3: EMA20-based
    ema20_sl = ema20 * (1 - buffer_pct)
    
    candidates = [
        (swing_low_sl, "Swing Low"),
        (vwap_sl, "VWAP"),
        (ema20_sl, "EMA20")
    ]
    
    # Filter: Only use SL below entry
    valid_candidates = [(sl, reason) for sl, reason in candidates if sl < entry_price]
    
    if not valid_candidates:
        return None, "No valid structure found", 0
    
    # --- NEW WATERFALL LOGIC ---
    
    # 1. Calc Dynamic Min SL first
    current_atr = df.iloc[-2].get('ATR')
    dynamic_min_sl = min_sl_distance
    
    if current_atr and current_atr > 0:
        atr_pct = (current_atr / entry_price) * 100
        dynamic_min = max(0.4, 0.6 * atr_pct)
        dynamic_min_sl = min(min_sl_distance, dynamic_min)

    # 2. Score & Filter Candidates
    enhanced_candidates = []
    normalized_priority = {"Swing Low": 3, "VWAP": 2, "EMA20": 1}
    
    for sl, r in valid_candidates:
        prio = normalized_priority.get(r, 0)
        dist_pct = ((entry_price - sl) / entry_price) * 100
        
        # Filter out Too Tight (< Min SL)
        if dist_pct < dynamic_min_sl:
            continue
            
        enhanced_candidates.append({"sl": sl, "reason": r, "prio": prio, "dist": dist_pct})

    if not enhanced_candidates:
        return None, f"All structures too tight (< {dynamic_min_sl:.2f}%)", 0.0

    # 3. Sort by Priority (High -> Low)
    enhanced_candidates.sort(key=lambda x: x["prio"], reverse=True)
    
    # 4. Select First within Max Distance
    for cand in enhanced_candidates:
         if cand["dist"] <= max_sl_distance:
             return cand["sl"], f"{cand['reason']} ({cand['dist']:.2f}%)", cand["dist"]
             
    # 5. Reject if all too wide
    best_candidate_dist = enhanced_candidates[0]["dist"]
    return None, f"All structures too wide (> {max_sl_distance}%)", best_candidate_dist

    # --- DEAD CODE BELOW (Short-Circuited) ---
    best_sl = entry_price # Dummy to prevent UnboundLocalError
    sl_distance_pct = 0
    
    # Safety Check: Dynamic Min SL based on ATR
    # Logic: max(0.4%, 0.6 * ATR%) to allow Large Caps with small ATR
    # Hard Min: 0.4% (to cover fees/slippage)
    
    current_atr = df.iloc[-2].get('ATR') # Use confirmed candle for ATR
    dynamic_min_sl = min_sl_distance # Default to config (0.8%)
    
    if current_atr and current_atr > 0:
        atr_pct = (current_atr / entry_price) * 100
        dynamic_min = max(0.4, 0.6 * atr_pct) # 0.6x ATR or 0.4% absolute min
        # Relax the strict 0.8% limit if ATR allows it
        dynamic_min_sl = min(min_sl_distance, dynamic_min) 
    
    if sl_distance_pct < dynamic_min_sl:
        return None, f"SL too tight ({sl_distance_pct:.2f}% < {dynamic_min_sl:.2f}%) - wick risk", sl_distance_pct
    
    # ----------------------------------------------------
    # SL FALLBACK LOGIC (Tightening if Swing Low > 2.0%)
    # ----------------------------------------------------
    if sl_distance_pct > max_sl_distance:
        # Swing Low SL is too wide. Try Fallbacks.
        # Fallback Buffer: 0.10% (0.001)
        fb_buffer = 0.001
        
        # 1. Try VWAP SL
        vwap_sl_price = vwap * (1 - fb_buffer)
        vwap_dist = ((entry_price - vwap_sl_price) / entry_price) * 100
        
        if vwap_sl_price < entry_price and vwap_dist <= max_sl_distance and vwap_dist >= dynamic_min_sl:
            return vwap_sl_price, f"SL_FALLBACK: SwingLow {sl_distance_pct:.2f}% too wide -> Using VWAP SL {vwap_dist:.2f}%", vwap_dist

        # 2. Try EMA20 SL
        ema_sl_price = ema20 * (1 - fb_buffer)
        ema_dist = ((entry_price - ema_sl_price) / entry_price) * 100
        
        if ema_sl_price < entry_price and ema_dist <= max_sl_distance and ema_dist >= dynamic_min_sl:
            return ema_sl_price, f"SL_FALLBACK: SwingLow {sl_distance_pct:.2f}% too wide -> Using EMA20 SL {ema_dist:.2f}%", ema_dist
            
        # If both fail -> REJECT
        return None, f"SL too wide ({sl_distance_pct:.2f}%) & Fallbacks invalid", sl_distance_pct
    
    return best_sl, f"{reason} ({sl_distance_pct:.2f}%)", sl_distance_pct


def calculate_structure_based_tp(entry_price, sl_price, df, previous_day_high=None, dynamic_resistances=None):
    """
    Calculate Take-Profit based on market structure.
    Priority: PDH > Pivot Res > Swing High > 1.5R minimum.
    
    Returns: (tp_price, tp_reason, risk_reward_ratio) or (None, reason, 0)
    """
    min_rr = config_manager.get("structure_risk", "min_risk_reward") or 1.5
    
    risk = entry_price - sl_price
    min_reward = risk * min_rr  # Minimum 1.5R
    min_tp = entry_price + min_reward
    
    candidates = []
    
    # Option 1: Previous Day High (if available and above entry)
    if previous_day_high and previous_day_high > entry_price:
        candidates.append((previous_day_high * 0.999, "PDH"))
        
    # Option 1.5: Dynamic Auto-Pivot Resistances
    if dynamic_resistances:
        for res in dynamic_resistances:
            if res > entry_price:
                dist_pct = ((res - entry_price) / entry_price) * 100
                if dist_pct >= 0.6:  # Minimum distance to avoid front-running chop
                    candidates.append((res * 0.999, "Pivot Res"))
    
    # Option 2: Nearest Swing High (last 20 candles)
    recent_candles = df.iloc[-20:]
    swing_high = recent_candles['high'].max()
    
    # Distance filter: Reject swing highs too close (< 0.6%)
    if swing_high > entry_price:
        distance_pct = ((swing_high - entry_price) / entry_price) * 100
        if distance_pct >= 0.6:  # Minimum 0.6% away to avoid front-running
            candidates.append((swing_high * 0.999, "Swing High"))
    
    # Option 3: 1.5R (Minimum acceptable)
    candidates.append((min_tp, "1.5R Minimum"))
    
    # Filter: Only TPs above entry
    valid_candidates = [(tp, reason) for tp, reason in candidates if tp > entry_price]
    
    if not valid_candidates:
        return None, "No valid target found", 0
    
    # Choose the NEAREST one (most realistic)
    best_tp, reason = min(valid_candidates, key=lambda x: x[0])
    
    # Calculate R:R
    reward = best_tp - entry_price
    rr_ratio = reward / risk if risk > 0 else 0
    
    # Reject if < 1.5R
    if rr_ratio < min_rr:
        return None, f"R:R too low ({rr_ratio:.2f})", rr_ratio
    
    return best_tp, f"{reason} (R:R {rr_ratio:.1f})", rr_ratio


def manage_positions(dhan, token_map):
    """
    Checks all active positions for SL, Target, and Trailing SL.
    Thread-Safe Implementation.
    """
    with state_lock:
        active_symbols = [s for s, p in BOT_STATE["positions"].items() if p["status"] == "OPEN"]
    
    if not active_symbols:
        return

    logger.info(f"Managing {len(active_symbols)} active positions...")

    current_time = time.strftime("%H:%M")
    
    # Fix: Use IST for Auto Square-Off Check (Render is UTC)
    try:
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
        current_time = ist_now.strftime("%H:%M")
    except Exception:
        pass # Fallback to local time if datetime fails (unlikely)

    square_off_time = config_manager.get("limits", "square_off_time") or "14:45"

    # --- BULK FETCH START ---
    live_prices = {}
    try:
        bulk_tokens = []
        # logger.info(f"Active Symbols: {active_symbols}") # DEBUG
        # logger.info(f"Token Map Sample: {list(token_map.keys())[:5]}") # DEBUG
        
        for s in active_symbols:
            t = token_map.get(s)
            if t:
                bulk_tokens.append(t)
            else:
                logger.warning(f"❌ Token MISSING for {s}")
        
        if bulk_tokens:
            live_prices = fetch_market_feed_bulk(dhan, bulk_tokens)
            # logger.info(f"Fetched live prices for {len(bulk_tokens)} tokens.")
            # logger.info(f"LIVE PRICES: {live_prices}") # DEBUG REMOVED
        else:
            # logger.warning("⚠️ No tokens found for bulk fetch!") # Only warn if truly empty and unexpected
            pass
    except Exception as e:
        logger.error(f"Bulk fetch error: {e}")
    # --- BULK FETCH END ---

    for symbol in active_symbols:
        token = token_map.get(symbol)
        
        if not token:
            continue

        try:
            # 0. Check Auto Square-Off Time (Use Config Value)
            if current_time >= square_off_time:
                logger.info(f"⏰ Time Limit Reached ({square_off_time}). Booking Profit/Loss for {symbol}...")
                
                # Fetch current LTP before closing
                time.sleep(0.2)  # Throttle
                # FIX: Use fetch_ltp and remove -EQ checks
                current_ltp_check = fetch_ltp(dhan, token, symbol)
                exit_price = 0
                
                if current_ltp_check is not None:
                    exit_price = current_ltp_check
                else:
                    logger.warning(f"Could not fetch LTP for TIME_EXIT. Using 0.")
                
                exit_qty = 0
                with state_lock:
                    pos = BOT_STATE["positions"].get(symbol)
                    if pos and pos["status"] == "OPEN" and not pos.get("exit_in_progress"):
                        pos["exit_in_progress"] = True
                        pos["exit_requested_ts"] = time.time()
                        exit_qty = pos['qty']
                
                if exit_qty > 0:
                    order_id, verified, exec_price = place_sell_order_with_retry(dhan, symbol, token, exit_qty, reason="TIME_EXIT")
                    
                    with state_lock:
                        pos = BOT_STATE["positions"].get(symbol)
                        
                        if pos and order_id and verified:
                            pos["exit_in_progress"] = False 
                            pos['status'] = "CLOSED"
                            pos['exit_price'] = exec_price if exec_price > 0 else exit_price 
                            pos['exit_reason'] = "TIME_EXIT"
                            
                            # --- P&L Calculation & Telegram ---
                            pnl = (pos['exit_price'] - pos['entry_price']) * pos['qty']
                            BOT_STATE["total_pnl"] = BOT_STATE.get("total_pnl", 0.0) + pnl
                            msg = f"🔴 **SELL EXECUTION (Time)**\nSymbol: {symbol}\nQty: {pos['qty']}\nBuy: {pos['entry_price']}\nSell: {pos['exit_price']}\nP&L: {pnl:.2f}\nTotal P&L: {BOT_STATE['total_pnl']:.2f}"
                            send_telegram_message(msg)
                            
                            save_state(BOT_STATE)
                        elif pos and order_id and not verified:
                             # Exits unverified: Don't close, but keep exit_in_progress=True to prevent duplicates
                             # Let Reconciliation or WebSocket clean it up.
                             logger.warning(f"⚠️ TIME_EXIT unverified for {symbol}. Waiting for confirmation.")
                             pass
                        elif pos:
                             # Placement failed
                             pos["exit_in_progress"] = False
                    
                    if order_id: # Log attempted exit even if unverified
                         # LOG TO SUPABASE 
                         leverage = get_leverage()
                         log_trade_execution(BOT_STATE["positions"].get(symbol), exit_price, "TIME_EXIT", leverage)
                continue

            # Current LTP Logic (Bulk Only - No Fallback)
            if str(token) in live_prices:
                current_ltp = live_prices[str(token)]
            else:
                # If bulk fetch failed or token missing, SKIP this cycle.
                # Fallback to single fetch causes 805 Rate Limit spiral.
                # logger.warning(f"LTP missing in bulk fetch for {symbol}. Skipping update.")
                continue
            
            if current_ltp is None:
                continue

            # ... (Rest of existing logic) ...
            # PRE-CALCULATE TECHNICAL INDICATORS (Outside Lock)
            # Fetching candles is an API call - must be done before acquiring lock
            tech_breakdown = False
            tech_reason_str = ""
            try:
                df_tech = fetch_candle_data(dhan, token, symbol, "FIVE_MINUTE")
                if df_tech is not None:
                    df_tech = calculate_indicators(df_tech)
                    
                if df_tech is not None and not df_tech.empty and len(df_tech) >= 2:
                    confirmed_candle = df_tech.iloc[-2]
                    close_price = confirmed_candle['close'] 
                    ema_20 = confirmed_candle.get('EMA_20')
                    vwap = confirmed_candle.get('VWAP')
                    
                    if ema_20 and vwap and not pd.isna(ema_20) and not pd.isna(vwap):
                        # DUAL CONFIRMATION: Price must close below BOTH indicators
                        if close_price < ema_20 and close_price < vwap:
                            tech_breakdown = True
                            tech_reason_str = f"Dual Breakdown (Close {close_price} < EMA {ema_20:.2f} & VWAP {vwap:.2f})"
            except Exception as e_tech:
                 logger.warning(f"Technical Exit Check failed for {symbol}: {e_tech}")

            # DECISION PHASE (Atomically check conditions)
            exit_action = None # (reason_code, qty, exit_reason_log)
            
            with state_lock:
                pos = BOT_STATE["positions"].get(symbol)
                
                # Check validity & exit_in_progress
                if not pos or pos["status"] != "OPEN": continue
                if pos.get("exit_in_progress"): continue

                entry_price = pos['entry_price']
                sl_price = pos['sl']
                target_price = pos.get('target')
                
                # UPDATE HIGHEST LTP
                pos['current_ltp'] = current_ltp
                if current_ltp > pos.get('highest_ltp', 0):
                    pos['highest_ltp'] = current_ltp

                # 1. HARD STOP LOSS
                if current_ltp <= sl_price:
                    logger.info(f"{symbol} Hit STOP LOSS at {current_ltp} (SL: {sl_price})")
                    exit_action = ("STOP_LOSS", pos['qty'], "STOP_LOSS")
                    pos["exit_in_progress"] = True
                    pos["exit_requested_ts"] = time.time()

                # 2. TARGET/TAKE PROFIT
                elif target_price and current_ltp >= target_price:
                    logger.info(f"🎯 {symbol} Hit TARGET at {current_ltp} (Target: {target_price})")
                    exit_action = ("TARGET_HIT", pos['qty'], "TARGET_HIT")
                    pos["exit_in_progress"] = True
                    pos["exit_requested_ts"] = time.time()

                # 3. TECHNICAL EXIT (Using pre-calculated flag)
                elif tech_breakdown:
                    logger.info(f"📉 {symbol} Technical Exit: {tech_reason_str}.")
                    exit_action = ("TECH_EXIT", pos['qty'], f"TECH_EXIT ({tech_reason_str})")
                    pos["exit_in_progress"] = True
                    pos["exit_requested_ts"] = time.time()

                # 4. TIME-BASED STAGNATION EXIT
                else:
                    entry_ts = pos.get('entry_time_ts')
                    if entry_ts:
                        duration_minutes = (time.time() - entry_ts) / 60
                        current_profit_pct = (current_ltp - entry_price) / entry_price
                        
                        if duration_minutes > 60 and current_profit_pct < 0.005: 
                            logger.info(f"💤 Time Exit: {symbol} Stagnant for {int(duration_minutes)}m. Closing.")
                            exit_action = ("TIME_EXIT", pos['qty'], "TIME_EXIT")
                            pos["exit_in_progress"] = True
                            pos["exit_requested_ts"] = time.time()
                
                # 5. CONTINUOUS TRAILING STOP LOSS (TSL)
                if not exit_action:
                    # Calculate original risk to define "1R"
                    original_sl = pos.get('original_sl', pos.get('sl')) 
                    
                    # Store original_sl safely if it doesn't exist yet
                    if 'original_sl' not in pos:
                        pos['original_sl'] = original_sl
                        
                    risk_per_share = entry_price - original_sl
                    
                    if risk_per_share > 0:
                        # Calculate the maximum R:R achieved at the absolute peak
                        highest_ltp = pos.get('highest_ltp', current_ltp)
                        max_profit_achieved = highest_ltp - entry_price
                        max_rr = max_profit_achieved / risk_per_share
                        
                        proposed_sl = pos['sl'] # Default to no movement
                        level_achieved = pos.get('tsl_level', 0)
                        
                        # --- Level 1: Breakeven (At 1R Profit) ---
                        if max_rr >= 1.0 and level_achieved < 1:
                            proposed_sl = entry_price * 1.001 # Entry + 0.1% to cover fees
                            new_level = 1
                            log_msg = f"🔒 Trailing SL Level 1: {symbol} hit +1R. SL moved to Breakeven ({proposed_sl:.2f})"
                            
                        # --- Level 2: Lock 1R (At 2R Profit) ---
                        elif max_rr >= 2.0 and level_achieved < 2:
                            proposed_sl = entry_price + (1.0 * risk_per_share)
                            new_level = 2
                            log_msg = f"🔒 Trailing SL Level 2: {symbol} hit +2R. SL moved to lock +1R ({proposed_sl:.2f})"
                            
                        # --- Level 3: Lock 2R (At 3R Profit) ---
                        elif max_rr >= 3.0 and level_achieved < 3:
                            proposed_sl = entry_price + (2.0 * risk_per_share)
                            new_level = 3
                            log_msg = f"🔒 Trailing SL Level 3: {symbol} hit +3R. SL moved to lock +2R ({proposed_sl:.2f})"
                        
                        # Update State if SL strictly moves UP
                        if proposed_sl > pos['sl']:
                            pos['sl'] = proposed_sl
                            pos['tsl_level'] = new_level
                            logger.info(log_msg)
                            save_state(BOT_STATE)
            # EXECUTION PHASE (Outside Lock)
            if exit_action:
                reason_code, qty, reason_log = exit_action
                order_id, verified, exec_price = place_sell_order_with_retry(dhan, symbol, token, qty, reason=reason_code)
                
                with state_lock:
                    pos = BOT_STATE["positions"].get(symbol)
                    
                    if pos and order_id and verified:
                        pos["exit_in_progress"] = False # Reset only on verified.
                        pos['status'] = "CLOSED"
                        pos['exit_price'] = exec_price if exec_price > 0 else current_ltp
                        pos['exit_reason'] = reason_code
                        
                        # --- P&L Calculation & Telegram ---
                        pnl = (pos['exit_price'] - pos['entry_price']) * pos['qty']
                        BOT_STATE["total_pnl"] = BOT_STATE.get("total_pnl", 0.0) + pnl
                        msg = f"🔴 **SELL EXECUTION**\nSymbol: {symbol}\nQty: {pos['qty']}\nBuy: {pos['entry_price']}\nSell: {pos['exit_price']}\nP&L: {pnl:.2f}\nTotal P&L: {BOT_STATE['total_pnl']:.2f}\nReason: {reason_code}"
                        send_telegram_message(msg)
                        
                        save_state(BOT_STATE)
                    elif pos and order_id and not verified:
                         logger.warning(f"⚠️ Exit {reason_code} unverified for {symbol}. Keep flag TRUE. Wait for sync.")
                         pass 
                    elif pos:
                         # Placement FAILED completely.
                         pos["exit_in_progress"] = False
                
                if order_id:
                    # LOG TO SUPABASE (Outside lock)
                    leverage = get_leverage()
                    log_trade_execution(BOT_STATE["positions"].get(symbol), current_ltp, reason_log, leverage)

        except Exception as e:
            logger.error(f"Error managing position {symbol}: {e}")

        except Exception as e:
            logger.error(f"Error managing position {symbol}: {e}")

from database import log_trade_execution

def reconcile_state(dhan):
    """
    Syncs BOT_STATE with Broker's Live Positions.
    Broker is the SOURCE OF TRUTH.
    Thread-Safe.
    """
    logger.info("Starting Startup Reconciliation...")
    try:
        live_positions = fetch_net_positions(dhan)
        if live_positions is None:
            logger.error("Reconciliation Failed: Could not fetch positions.")
            return False # Failure

        # 1. Map Live Positions (Only Open ones)
        broker_open_positions = {}
        for pos in live_positions:
            qty = int(pos.get("netqty", 0))
            if qty != 0:
                symbol = pos.get("tradingsymbol", "").replace("-EQ", "")
                broker_open_positions[symbol] = {
                    "qty": abs(qty),
                    "avg_price": float(pos.get("avgnetprice", 0)),
                    "token": pos.get("symboltoken")
                }

        # CRITICAL SECTION
        with state_lock:
            # 2. Check for ORPHANS (In Broker, Not in Bot)
            for symbol, data in broker_open_positions.items():
                if symbol not in BOT_STATE["positions"] or BOT_STATE["positions"][symbol]["status"] != "OPEN":
                    logger.warning(f"⚠️ Found ORPHAN Trade: {symbol} (Qty: {data['qty']}). Importing...")
                    
                    # Import into State (Applying Default Risk to avoid Blow-up)
                    sl_pct = config_manager.get("risk", "stop_loss_pct") or 0.01
                    tp_pct = config_manager.get("risk", "target_pct") or 0.02
                    
                    BOT_STATE["positions"][symbol] = {
                        "entry_price": data['avg_price'],
                        "qty": data['qty'],
                        "sl": data['avg_price'] * (1 - sl_pct),
                        "target": data['avg_price'] * (1 + tp_pct),
                        "status": "OPEN",
                        "entry_time": "RECONCILED",
                        "setup_grade": "ORPHAN",
                        "is_orphaned": True
                    }
                    save_state(BOT_STATE)

            # 3. Check for GHOSTS (In Bot (OPEN), Not in Broker)
            for symbol, pos in list(BOT_STATE["positions"].items()):
                if pos["status"] == "OPEN":
                    if symbol not in broker_open_positions:
                        logger.warning(f"👻 Found GHOST Trade: {symbol}. Marking CLOSED.")
                        pos["status"] = "CLOSED"
                        pos["exit_reason"] = "RECONCILIATION_MISSING"
                        pos["exit_price"] = 0 # Unknown
                        save_state(BOT_STATE)

        logger.info("Reconciliation Complete. State Synced. ✅")
        
    except Exception as e:
        logger.error(f"Error during Reconciliation: {e}")
        return False # Failure
    
    return True # Success

def reconcile_positions_quick(dhan):
    """
    Lightweight reconciliation - open positions only.
    Runs every 60s to catch orphans/ghosts mid-day.
    """
    try:
        live_positions = fetch_net_positions(dhan)
        if live_positions is None:
            logger.warning("Quick reconciliation: Failed to fetch positions")
            return
        
        # Empty list is valid - means broker has no open positions
        
        # Build map of broker's open positions
        broker_open = {}
        for pos in live_positions:
            qty = int(pos.get("netqty", 0))
            if qty != 0:
                symbol = pos.get("tradingsymbol", "").replace("-EQ", "")
                broker_open[symbol] = {
                    "qty": abs(qty),
                    "avg_price": float(pos.get("avgnetprice", 0)),
                    "token": pos.get("symboltoken")
                }
        
        with state_lock:
            # Check for ghosts (in bot, not in broker)
            for symbol, pos in list(BOT_STATE["positions"].items()):
                if pos["status"] == "OPEN" and symbol not in broker_open:
                    logger.warning(f"👻 Ghost detected: {symbol}. Marking closed.")
                    pos["status"] = "CLOSED"
                    pos["exit_reason"] = "RECONCILIATION"
                    
            # Check for orphans (in broker, not in bot)
            for symbol, data in broker_open.items():
                if symbol not in BOT_STATE["positions"] or BOT_STATE["positions"][symbol]["status"] != "OPEN":
                    logger.warning(f"⚠️ Orphan detected: {symbol} (Qty: {data['qty']}). Importing...")
                    
                    # CRITICAL: Use EMERGENCY SL (tight) to prevent blow-up
                    # Config defaults might be too wide for unknown positions
                    emergency_sl_pct = 0.008  # 0.8% for equity (conservative)
                    emergency_tp_pct = 0.02   # 2% target (optimistic)
                    
                    logger.warning(f"🚨 Applying EMERGENCY SL: {emergency_sl_pct*100}% for orphan {symbol}")
                    
                    BOT_STATE["positions"][symbol] = {
                        "symbol": symbol,
                        "entry_price": data['avg_price'],
                        "qty": data['qty'],
                        "sl": data['avg_price'] * (1 - emergency_sl_pct),
                        "target": data['avg_price'] * (1 + emergency_tp_pct),
                        "original_sl": data['avg_price'] * (1 - emergency_sl_pct),
                        "highest_ltp": data['avg_price'],
                        "status": "OPEN",
                        "entry_time": "RECONCILED",
                        "entry_time_ts": time.time(),
                        "is_breakeven_active": False,
                        "is_orphaned": True,
                        "exit_in_progress": False  # Initialize exit tracking
                    }
                    
                save_state(BOT_STATE)
        
    except Exception as e:
        logger.exception(f"Quick reconciliation error: {e}")

import asyncio

# ... imports ...

def run_bot_loop(async_loop=None, ws_manager=None):
    """
    Background task to run the bot loop.
    Accepts async_loop and ws_manager to broadcast updates via WebSockets.
    """
    global BOT_STATE, DHAN_API_SESSION, TOKEN_MAP
    BOT_STATE["is_running"] = True
    
    logger.info("Starting Auto Buy/Sell Bot...")

    # Helper to broadcast updates
    def broadcast_state():
        if async_loop and ws_manager:
            try:
                # Inject Heartbeat for Frontend Debugging
                BOT_STATE["last_heartbeat"] = time.time()
                
                # logger.info("Broadcasting State Update...") 
                future = asyncio.run_coroutine_threadsafe(ws_manager.broadcast(BOT_STATE), async_loop)
                
                # Check for exceptions in the async task (Critical for debugging serialization errors)
                def check_error(f):
                    try:
                        if f.exception():
                            logger.error(f"WS Broadcast Async Error: {f.exception()}")
                    except:
                        pass
                        
                future.add_done_callback(check_error)
                
            except Exception as e:
                logger.error(f"WS Broadcast Failed: {e}")

    # --- Position Manager Thread ---
    def run_position_manager(api_session, t_map):
        logger.info("🚀 Starting Real-Time Position Manager Thread...")
        while BOT_STATE.get("is_running", True):
            try:
                # Update Heartbeat
                BOT_STATE.setdefault("heartbeat", {})["position_manager"] = time.time()
                
                # Check Market Status
                is_open, _ = is_market_open()
                if not is_open:
                    time.sleep(60)
                    continue

                # Run every 5 seconds for fast updates
                # Use global session to pick up re-authenticated sessions
                manage_positions(DHAN_API_SESSION, t_map)
                
                # Broadcast updates immediately after management
                broadcast_state()
                
                # Adaptive polling: 1s if recent entry, else 5s
                # Reduces SL slippage for fresh positions
                with state_lock:
                    has_fresh_position = any(
                        (time.time() - pos.get('entry_time_ts', 0)) < 30
                        for pos in BOT_STATE['positions'].values()
                        if pos['status'] == 'OPEN'
                    )
                
                interval = 1 if has_fresh_position else 5
                time.sleep(interval)
            except Exception as e:
                logger.exception(f"Position Manager Thread Error: {e}")
                time.sleep(5)
    # -------------------------------

    # ... (SmartAPI Init) ...
    # 1. Initialize Dhan API
    dhan = get_dhan_session()
    if not dhan:
        logger.critical("Failed to connect to Dhan API. Exiting.")
        BOT_STATE["is_running"] = False
        return
    
    DHAN_API_SESSION = dhan 
    dhan = dhan  # Legacy alias - to be refactored eventually 

    # 2. Load Dhan Instrument Map
    token_map = load_dhan_instrument_map()
    if not token_map:
        logger.critical("Failed to load Dhan Token Map. Exiting.")
        BOT_STATE["is_running"] = False
        return
        
    TOKEN_MAP = token_map

    # 3. Start Position Manager Thread
    pm_thread = threading.Thread(target=run_position_manager, args=(dhan, token_map), daemon=True)
    pm_thread.start()

    # 3.5. Start Continuous Reconciliation Thread
    def run_reconciliation_loop():
        time.sleep(10)  # Initial delay to let bot initialize
        while BOT_STATE.get("is_running", True):
            try:
                BOT_STATE.setdefault("heartbeat", {})["reconciliation"] = time.time()
                
                # Check Market Status
                is_open, _ = is_market_open()
                if not is_open:
                    time.sleep(60)
                    continue

                # Use global session to pick up re-authenticated sessions
                reconcile_positions_quick(DHAN_API_SESSION)
                time.sleep(60)  # Every 60 seconds
            except Exception as e:
                logger.exception(f"Reconciliation Loop Error: {e}")
                time.sleep(60)
    
    recon_thread = threading.Thread(target=run_reconciliation_loop, daemon=True, name="Reconciliation")
    recon_thread.start()
    logger.info("✅ Continuous Reconciliation started (60s interval)")

    # 3.6. Start Pending Order Cleanup Thread
    def run_cleanup_loop():
        time.sleep(60)  # Initial delay
        while BOT_STATE.get("is_running", True):
            try:
                BOT_STATE.setdefault("heartbeat", {})["cleanup"] = time.time()
                
                # Check Market Status (Cleanup might be allowed post-market, but let's restrict to save API)
                is_open, _ = is_market_open()
                if not is_open:
                     time.sleep(60)
                     continue

                # Use global session to pick up re-authenticated sessions
                cleanup_pending_orders(DHAN_API_SESSION)
                time.sleep(300)  # Every 5 minutes
            except Exception as e:
                logger.exception(f"Cleanup Loop Error: {e}")
                time.sleep(300)
    
    cleanup_thread = threading.Thread(target=run_cleanup_loop, daemon=True, name="Cleanup")
    cleanup_thread.start()
    logger.info("✅ Pending Order Cleanup started (5min interval)")

    # 3.7. Start Heartbeat Watchdog (Safety System)
    def run_heartbeat_watchdog():
        """
        Monitors health of critical threads.
        Stops trading if any thread stalls > 120s.
        """
        time.sleep(30) # Initial warmup delay
        logger.info("🛡️ Heartbeat Watchdog Active")
        
        while BOT_STATE.get("is_running", True):
            try:
                current_time = time.time()
                heartbeats = BOT_STATE.get("heartbeat", {})
                
                # Check critical threads
                critical_threads = ["position_manager", "reconciliation"] # Removed 'websocket' as it blocks internally w/o reliable heartbeat
                
                for thread_name in critical_threads:
                    last_beat = heartbeats.get(thread_name, 0)
                    # Ignore if last_beat is 0 (thread might not have started or updated yet?)
                    # No, threads update immediately. 
                    # Use a stricter check? If 0, it's suspicious after warmup.
                    
                    if last_beat > 0 and (current_time - last_beat) > 120:
                        logger.critical(f"🚨 CRITICAL: Thread '{thread_name}' stalled! Last heartbeat {int(current_time - last_beat)}s ago.")
                        logger.critical("🛑 STOPPING NEW ENTRIES (Circuit Breaker Triggered)")
                        BOT_STATE["is_trading_allowed"] = False
                        # We don't stop the bot process to ensure we can still manage exiting positions if possible.
                        
                time.sleep(60) # Check every minute
            except Exception as e:
                logger.error(f"Watchdog Error: {e}")
                time.sleep(60)

    watchdog_thread = threading.Thread(target=run_heartbeat_watchdog, daemon=True, name="Watchdog")
    watchdog_thread.start()

    # 3.8. Start Sniper Execution Loop Thread
    def run_sniper_execution_loop(api_session, t_map):
        time.sleep(15) # Wait for bot to initialize
        logger.info("🎯 Sniper Execution Thread started (45s interval)")
        while BOT_STATE.get("is_running", True):
            try:
                BOT_STATE.setdefault("heartbeat", {})["sniper_execution"] = time.time()
                
                # Check Market Status
                is_open, _ = is_market_open()
                if not is_open:
                    time.sleep(60)
                    continue
                    
                # Check Trading Limits
                trading_end_time = config_manager.get("limits", "trading_end_time")
                trading_start_time = config_manager.get("limits", "trading_start_time") or "09:45"
                current_time = get_ist_now().strftime("%H:%M")
                
                if current_time < trading_start_time or current_time >= trading_end_time:
                    time.sleep(60)
                    continue
                from indicators import check_1m_sniper_entry, calculate_indicators
                
                watchlist = BOT_STATE.get("sniper_watchlist", {})
                expired_symbols = []
                dry_run = config_manager.get("general", "dry_run") or False
                max_trades_day = config_manager.get("limits", "max_trades_per_day") or 3
                
                for symbol, data in list(watchlist.items()):
                     # 1. Prune Expired (Older than 15 mins)
                     if time.time() - data["added_at"] > 900:
                         logger.info(f"⏳ Sniper Watchlist Timeout: Removed {symbol} (No pullback within 15min)")
                         expired_symbols.append(symbol)
                         continue
                         
                     # 2. Prevent Multiple Positions
                     if symbol in BOT_STATE.get("positions", {}) and BOT_STATE["positions"][symbol].get("status") == "OPEN":
                         expired_symbols.append(symbol)
                         continue
                         
                     # 3. Check Trading Limits dynamically again before executing
                     if BOT_STATE.get("total_trades_today", 0) >= max_trades_day:
                         break
                         
                     # 4. Idempotency Check (Prevent duplicate orders on aggressive loop)
                     correlation_id = generate_correlation_id(symbol, "SNIPER_BUY")
                     from main import is_order_inflight # Check pending by symbol
                     if is_order_inflight(symbol):
                         logger.warning(f"⏩ Skipping {symbol} Snipe: Order already pending execution.")
                         expired_symbols.append(symbol) # Clear it since an order is already flying
                         continue
                         
                     token = t_map.get(symbol)
                     if not token:
                         continue
                         
                     # Re-fetch latest 5M for VWAP/EMA20 anchors
                     df_5m = fetch_candle_data(api_session, token, symbol, "FIVE_MINUTE")
                     if df_5m is None or len(df_5m) < 2: continue
                     
                     df_5m = calculate_indicators(df_5m)
                     latest_5m = df_5m.iloc[-2]
                     five_m_vwap = latest_5m.get('VWAP')
                     five_m_ema20 = latest_5m.get('EMA_20')
                     
                     if pd.isna(five_m_vwap) or pd.isna(five_m_ema20): continue
                     
                     # Check 1M Pullback
                     df_1m = fetch_candle_data(api_session, token, symbol, "ONE_MINUTE")
                     if df_1m is not None:
                         impulse_time = data.get('impulse_time')
                         impulse_vol = data.get('impulse_vol', 0)
                         nifty_1m_state = BOT_STATE.get("nifty_1m")
                         
                         is_snipe, snipe_reason = check_1m_sniper_entry(
                             df_1m, 
                             five_m_vwap, 
                             five_m_ema20, 
                             impulse_time=impulse_time,
                             impulse_vol=impulse_vol,
                             nifty_1m_state=nifty_1m_state
                         )
                         
                         if is_snipe:
                             logger.info(f"🔫 SNIPER EXECUTING {symbol}: {snipe_reason}")
                             expired_symbols.append(symbol)
                             
                             recent_1m = df_1m.iloc[-6:-1]
                             sl_price = recent_1m['low'].min()
                             buffered_sl = sl_price * 0.999
                             
                             live_ltp = fetch_ltp(api_session, token, symbol)
                             if live_ltp is None or live_ltp == 0:
                                  logger.warning(f"LTP missing for sniper {symbol}")
                                  continue
                                  
                             if live_ltp <= buffered_sl:
                                  logger.warning(f"Invalid Sniper SL for {symbol}. LTP: {live_ltp} SL: {buffered_sl}")
                                  continue
                                  
                             try:
                                  balance = get_account_balance(api_session, dry_run)
                             except Exception:
                                  balance = 100000.0  # Fallback
                                  
                             risk_pct = config_manager.get("position_sizing", "risk_per_trade_pct") or 1.0
                             max_pos_pct = config_manager.get("position_sizing", "max_position_size_pct") or 20.0
                             min_sl_pct = config_manager.get("position_sizing", "min_sl_distance_pct") or 0.5
                             
                             calc_qty = calculate_position_size(
                                  entry_price=live_ltp,
                                  sl_price=buffered_sl,
                                  balance=balance,
                                  risk_pct=risk_pct,
                                  max_position_pct=max_pos_pct,
                                  min_sl_pct=min_sl_pct,
                                  symbol=symbol
                             )
                             
                             if calc_qty > 0:
                                  from main import check_and_register_pending_order
                                  
                                  if not check_and_register_pending_order(correlation_id, {"symbol": symbol, "type": "BUY"}):
                                      logger.warning(f"⏩ {symbol}: Blocked by concurrency/pending order check.")
                                      continue
                                      
                                  order_id = place_buy_order(api_session, symbol, token, calc_qty, correlation_id=correlation_id)
                                  
                                  if order_id or dry_run:
                                      target_pct = config_manager.get("risk", "target_pct") or 0.02
                                      target_price = live_ltp * (1 + target_pct) 
                                      
                                      with state_lock:
                                           BOT_STATE["total_trades_today"] += 1
                                           BOT_STATE["stock_trade_counts"][symbol] = BOT_STATE["stock_trade_counts"].get(symbol, 0) + 1
                                           BOT_STATE["positions"][symbol] = {
                                                "symbol": symbol,
                                                "entry_price": live_ltp,
                                                "qty": calc_qty,
                                                "sl": buffered_sl,
                                                "target": target_price,
                                                "original_sl": buffered_sl,
                                                "highest_ltp": live_ltp,
                                                "status": "OPEN",
                                                "entry_time": get_ist_now().strftime("%H:%M:%S"),
                                                "entry_time_ts": time.time(),
                                                "is_breakeven_active": False,
                                                "setup_grade": "SNIPER",
                                                "order_id": order_id if not dry_run else "DRY_RUN",
                                                "exit_in_progress": False
                                           }
                                           save_state(BOT_STATE)
                                           broadcast_state()
                                           
                                           from main import clear_pending_order
                                           clear_pending_order(correlation_id)
                                           
                                      leverage = get_leverage()      
                                      try:
                                          log_trade_execution(BOT_STATE["positions"][symbol], 0, "BUY", leverage)
                                      except Exception as ex:
                                          logger.error(f"Failed to log trade to Supabase: {ex}")
                                      
                                      msg = f"🟢 **SNIPER EXECUTED**\nSymbol: {symbol}\nQty: {calc_qty}\nLTP: ₹{live_ltp:.2f}\nRisk SL: ₹{buffered_sl:.2f} \nDist: {((live_ltp-buffered_sl)/live_ltp)*100:.2f}%\nStatus: {'PAPER TRADING' if dry_run else 'LIVE'}"
                                      send_telegram_message(msg)
                                  else:
                                      # Order failed to place, clear lock
                                      from main import clear_pending_order
                                      clear_pending_order(correlation_id)

                # Prune explicitly removed / expired watchlist items
                if expired_symbols:
                    with state_lock:
                        for s in expired_symbols:
                            if s in BOT_STATE.get("sniper_watchlist", {}):
                                del BOT_STATE["sniper_watchlist"][s]
                        save_state(BOT_STATE)
                        
                time.sleep(45)  # Fast Sniper Watchlist Poll loop limit
            except Exception as e:
                logger.exception(f"Sniper Execution Loop Error: {e}")
                time.sleep(45)

    sniper_thread = threading.Thread(target=run_sniper_execution_loop, args=(dhan, token_map), daemon=True, name="SniperLoop")
    sniper_thread.start()

    # 4. Start Dhan Order WebSocket (Real-time Updates)
    try:
        logger.info("Initializing Dhan Order WebSocket...")
        from dhan_websocket import start_dhan_websocket
        start_dhan_websocket(BOT_STATE)
    except Exception as e:
        logger.error(f"Failed to start Dhan Order WebSocket: {e}")

    try:
        while True:
            logger.info("Starting Main Loop Iteration...")
            try:
                # Fix: Use IST implementation for Logic Checks (Render is UTC)
                ist_now = get_ist_now()
                current_time = ist_now.strftime("%H:%M")
                BOT_STATE["last_update"] = ist_now.strftime("%H:%M:%S")
                
                # BROADCAST UPDATE (Heartbeat/Status)
                broadcast_state()
    
                # --- Market Schedule Check ---
                is_open, reason = is_market_open()
                if not is_open:
                    logger.info(f"Market Closed ({reason}). Sleeping for 60s...")
                    time.sleep(60) 
                    # Still broadcast while sleeping occasionally?
                    continue
                # -----------------------------
                
                # ... (Rest of logic) ...
                
                # --- Daily Signal Reset (Also resets reconciliation flag) ---
                from state_manager import check_and_reset_daily_signals
                check_and_reset_daily_signals(BOT_STATE)
                # --------------------------
                
                # --- Reconciliation (Only Once Per Day in Live Mode) ---
                dry_run = config_manager.get("general", "dry_run") or False
                reconciliation_done = BOT_STATE.get("reconciliation_done_today", False)
                
                if DHAN_API_SESSION and not dry_run and not reconciliation_done:
                     logger.info("🔄 Running Daily Reconciliation...")
                     success = reconcile_state(DHAN_API_SESSION)
                     if success:
                         BOT_STATE["reconciliation_done_today"] = True
                         save_state(BOT_STATE)
                     else:
                         logger.warning("Reconciliation Failed. Attempting to Re-Authenticate...")
                         new_session = get_dhan_session()
                         if new_session:
                             DHAN_API_SESSION = new_session
                             dhan = new_session # Update local reference
                             logger.info("Session Re-established successfully. ✅")
                         else:
                             logger.error("Session Re-authentication Failed. Will retry next cycle.")
                elif dry_run:
                    # Dry Run Mode - Skip reconciliation
                    pass
                elif reconciliation_done:
                    # Already reconciled today
                    pass
                
                # ----------------------

                # --- 🔍 TOKEN HEALTH CHECK ---
                from dhan_api_helper import check_connection
                if dhan:
                    is_valid, reason = check_connection(dhan)
                    if not is_valid:
                         if reason == "TOKEN_EXPIRED":
                             logger.critical("🚨 DHAN TOKEN EXPIRED! PAUSING BOT. UPDATE CONFIG.")
                             BOT_STATE["is_trading_allowed"] = False
                             BOT_STATE["error"] = "Token Expired"
                         else:
                             logger.warning(f"⚠️ API Connection Unstable: {reason}")
                # -----------------------------
                
                # --- Daily Signal Reset ---
                from state_manager import check_and_reset_daily_signals
                check_and_reset_daily_signals(BOT_STATE)
                # --------------------------
    
                # --- Manage Active Positions ---
                # Moved to dedicated thread for real-time updates!
                # manage_positions(dhan, token_map)
                # -------------------------------
                
                # BROADCAST AFTER MANAGEMENT (Price updates, exits)
                broadcast_state()
    
                # ... (Trade Guards) ...
                trading_end_time = config_manager.get("limits", "trading_end_time")
                trading_start_time = config_manager.get("limits", "trading_start_time") or "09:45"
                max_trades_day = config_manager.get("limits", "max_trades_per_day")
                max_trades_stock = config_manager.get("limits", "max_trades_per_stock")
                quantity = config_manager.get("general", "quantity")
                check_interval = config_manager.get("general", "check_interval")
    
                # Update State with Config Limits for Frontend
                BOT_STATE["limits"] = {
                    "max_trades_day": max_trades_day,
                    "max_trades_stock": max_trades_stock,
                    "trading_end_time": trading_end_time,
                    "trading_start_time": trading_start_time
                }
    
                if not BOT_STATE["is_trading_allowed"]:
                    time.sleep(10)
                    continue
                    
                # --- Fetch Market Indices (New) ---
                # 1. Fetch NIFTY 50 1M Data for Sniper Market Participation Filter
                try:
                    # Token for Nifty 50 Index on Dhan is "13"
                    nifty_token = "13" if "Nifty 50" not in token_map else token_map["Nifty 50"]
                    # If token_map doesn't have it explicitly mapped by that name, '13' is the known IDX_I token.
                    # Fallback to direct symbol token.
                    nifty_df = fetch_candle_data(dhan, nifty_token, "NIFTY 50", "ONE_MINUTE")
                    if nifty_df is not None and len(nifty_df) > 20:
                        from indicators import calculate_indicators
                        nifty_df = calculate_indicators(nifty_df)
                        latest_nifty = nifty_df.iloc[-1]
                        
                        BOT_STATE["nifty_1m"] = {
                            "close": latest_nifty.get('close', 0),
                            "ema20": latest_nifty.get('EMA_20', 0),
                            "timestamp": time.time()
                        }
                    else:
                        logger.warning("Failed to fetch/calculate NIFTY 50 1M for market participation filter.")
                except Exception as e_nifty:
                    logger.error(f"Error fetching NIFTY 1M data: {e_nifty}")
    
                # 2. Fetch General Indices for UI
                indices = fetch_market_indices()
                if indices:
                    BOT_STATE["indices"] = indices
                    
                # --- Pre-Fetch Top Sectors for UI (Always, regardless of strategy mode) ---
                strategy_mode = config_manager.get("general", "strategy_mode") or "SECTOR_MOMENTUM"
                sectors = fetch_top_performing_sectors()
                if sectors:
                    BOT_STATE["top_sectors"] = sectors[:4] # Store top 4 for UI
                
                broadcast_state() # Update UI with indices & sectors
                # ----------------------------------

                if current_time < trading_start_time:
                    logger.info(f"Market Open. Indices/Sectors Updated. Waiting for Strategy Start Time ({trading_start_time})...")
                    time.sleep(60)
                    continue
    
                if current_time >= trading_end_time:
                    time.sleep(60) 
                    continue
    
                if BOT_STATE["total_trades_today"] >= max_trades_day:
                    time.sleep(60)
                    continue
                
                # --- STRATEGY SELECTION ---
                # strategy_mode already fetched above
                
                stocks_to_scan = []
                seen_symbols = set()

                if strategy_mode == "MARKET_MOVER":
                    logger.info("⚡ Strategy: Market Movers (Top Gainers)")
                    try:
                        from market_mover import fetch_market_movers
                        # Fetch Top 50 Gainers to ensure enough candidates
                        raw_movers = fetch_market_movers("Gainer")
                        
                        if raw_movers:
                             logger.info(f"Fetched {len(raw_movers)} market movers. Top: {[m['symbol'] for m in raw_movers[:5]]}")
                             
                             # Log to Supabase (Async to avoid blocking)
                             from database import log_market_movers_to_db
                             threading.Thread(target=log_market_movers_to_db, args=(raw_movers[:15],)).start()
                        
                        for stock in raw_movers:
                            symbol = stock['symbol']
                            
                            if symbol in seen_symbols: continue
                            seen_symbols.add(symbol)
                            
                            # Skip if Position Open
                            if symbol in BOT_STATE["positions"] and BOT_STATE["positions"][symbol]["status"] == "OPEN":
                                continue
                                
                            # Skip if Stock limits hit
                            current_stock_trades = BOT_STATE["stock_trade_counts"].get(symbol, 0)
                            if current_stock_trades >= max_trades_stock:
                                continue
                                
                            stock['sector'] = "Market Mover"
                            stocks_to_scan.append(stock)
                            
                            # Limit scanning to top 15 candidates as per user request
                            if len(stocks_to_scan) >= 15: break
                            
                    except Exception as e_mover:
                        logger.error(f"Market Mover Strategy Failed: {e_mover}")

                else:
                    # DEFAULT: SECTOR MOMENTUM
                    if sectors:
                         logger.info(f"DEBUG: Main Loop Scraped {len(sectors)} sectors. Top: {[s['name'] for s in sectors[:4]]}")
                    else:
                        logger.info("No sector data available. Skipping scan. 📉")
                    
                    target_sectors = sectors[:4] if sectors else []
        
                    for sector in target_sectors:
                        stocks = fetch_stocks_in_sector(sector['key'])
                        for stock in stocks:
                            symbol = stock['symbol']
                            
                            if symbol in seen_symbols: continue
                            seen_symbols.add(symbol)
                            
                            if symbol in BOT_STATE["positions"] and BOT_STATE["positions"][symbol]["status"] == "OPEN":
                                continue
                                
                            current_stock_trades = BOT_STATE["stock_trade_counts"].get(symbol, 0)
                            if current_stock_trades >= max_trades_stock:
                                continue
                            
                            stock['sector'] = sector['name']
                            stocks_to_scan.append(stock)
    
                if BOT_STATE["total_trades_today"] >= max_trades_day:
                    time.sleep(60)
                    continue
    
                # -- ASYNC BATCH SCAN --
                if stocks_to_scan:
                    # Initialize Scanner with fresh SmartAPI Session Object
                    # Legacy: Pass token. New: Pass dhan object for robustness.
                    scanner = AsyncScanner("UNUSED_TOKEN", smartApi=dhan)
                    
                    # Fetch Persistent Index Memory (High/Low Cache)
                    # This fixes the "Post-Market 0.0" data issue by remembering valid High/Low from earlier.
                    index_memory = BOT_STATE.setdefault("index_memory", {})
                    
                    try:
                        # Run Async Scan (Blocking Call)
                        # Protected against Event Loop conflicts
                        signals = asyncio.run(scanner.scan(stocks_to_scan, token_map, index_memory))
                    except RuntimeError as re:
                         # This catches "asyncio.run() cannot be called from a running event loop"
                         logger.critical(f"CRITICAL ASYNCIO ERROR: {re}. Is the bot passing an existing loop?")
                         # Fallback: Try using the existing loop if available (dangerous but worth a shot in emergency)
                         # For now, just skip scan to keep bot alive
                         signals = []
                    except Exception as e:
                         logger.error(f"Scanner Crash: {e}")
                         signals = []
                
                # Save Updated Memory (Logic in Scanner updates the dict in-place)
                save_state(BOT_STATE) 
                
                # Process Signals Sequentially
                for signal_data in signals:
                    symbol = signal_data['symbol']
                    message = signal_data['message']
                    price = signal_data['price']
                    
                    # Check Daily Limit again (in case multiple signals triggered)
                    if BOT_STATE["total_trades_today"] >= max_trades_day: 
                        break
    
                    # Record Signal
                    if not any(s['symbol'] == symbol and s['time'] == signal_data['time'] for s in BOT_STATE['signals']):
                        BOT_STATE['signals'].insert(0, signal_data)
                        if len(BOT_STATE['signals']) > 50: BOT_STATE['signals'] = BOT_STATE['signals'][:50]
                        broadcast_state()
    
                        # --- SNIPER ALERT REGISTRATION ---
                        if message.startswith("SNIPER_ALERT"):
                            # STRICT TIME CHECK: Do not enter new trades outside the allowed trading window
                            trading_start_time = config_manager.get("limits", "trading_start_time") or "09:45"
                            trading_end_time = config_manager.get("limits", "trading_end_time") or "11:45"
                            ist_now = get_ist_now()
                            current_time_str = ist_now.strftime("%H:%M")
                            if current_time_str < trading_start_time or current_time_str >= trading_end_time:
                                logger.info(f"⏳ Ignoring Sniper Alert for {symbol}: Current time {current_time_str} is outside trading window ({trading_start_time} - {trading_end_time}).")
                                continue
                                
                            current_trades = len([p for p in BOT_STATE["positions"].values() if p["status"] == "OPEN"])
                            if current_trades < max_trades_day:
                                # Add to Watchlist
                                with state_lock:
                                    if symbol not in BOT_STATE.get("sniper_watchlist", {}):
                                        logger.info(f"🎯 Sniper Alert Registered for {symbol} at {price}. Waiting for 1M Pullback...")
                                        
                                        # Use signal_data['time'] if available, else current time
                                        # To accurately track 5M candle freshness
                                        impulse_time = pd.to_datetime(signal_data.get('time', "now")).timestamp() if 'time' in signal_data else time.time()
                                        
                                        # Extract Volume from message if present (Format: "... | Vol: 12345")
                                        impulse_vol = 0
                                        if "| Vol:" in message:
                                            try:
                                                impulse_vol = float(message.split("| Vol:")[1].strip())
                                            except Exception:
                                                pass
                                        
                                        if "sniper_watchlist" not in BOT_STATE:
                                            BOT_STATE["sniper_watchlist"] = {}
                                        BOT_STATE["sniper_watchlist"][symbol] = {
                                            "added_at": time.time(),
                                            "impulse_time": impulse_time,
                                            "impulse_vol": impulse_vol,
                                            "5m_vwap": 0.0, # Will fetch real latest later before pullback execution,
                                            "5m_ema20": 0.0,
                                        }
                                        
                                save_state(BOT_STATE)
                                
                        # --- AUTO BUY LOGIC (Structure-Based Risk) ---
                        if message.startswith("Strong Buy"):

                            current_trades = len([p for p in BOT_STATE["positions"].values() if p["status"] == "OPEN"])
                            if current_trades < max_trades_day:
                                logger.info(f"🚀 Evaluating BUY for {symbol} at {price}")
                                
                                token = token_map.get(symbol)
                                if token:
                                    use_structure = config_manager.get("structure_risk", "use_structure_based") or False
                                    
                                    if use_structure:
                                        # STEP 1: Re-validate 15M Bias (The Golden Rule)
                                        # Signals could be queued, market may have changed since scanner ran
                                        df_15m_recheck = fetch_candle_data(dhan, token, symbol, "FIFTEEN_MINUTE")
                                        
                                        if df_15m_recheck is None or df_15m_recheck.empty:
                                            logger.warning(f"❌ Skipping {symbol}: Unable to fetch 15M data for re-validation")
                                            continue
                                        
                                        from indicators import check_15m_bias, calculate_indicators
                                        df_15m_recheck = calculate_indicators(df_15m_recheck)
                                        bias_15m, bias_reason = check_15m_bias(df_15m_recheck)
                                        
                                        if bias_15m != 'BULLISH':
                                            logger.warning(f"❌ Trade REJECTED: {symbol} | 15M bias changed to {bias_15m} ({bias_reason})")
                                            continue
                                        
                                        logger.info(f"✅ 15M Bias Confirmed: {symbol} | {bias_reason}")
                                        
                                        # STEP 1.5: S/R Resistance Check (New)
                                        # Use the 15m data (multi-day) to find static S/R (PDH/CDH)
                                        from indicators import calculate_sr_levels, get_dynamic_sr_levels
                                        sr_levels = calculate_sr_levels(df_15m_recheck)
                                        
                                        static_resistances = []
                                        pdh_val = None
                                        if sr_levels:
                                            pdh_val = sr_levels.get('PDH')
                                            cdh_val = sr_levels.get('CDH')
                                            if pdh_val and pdh_val > price: static_resistances.append(pdh_val)
                                            if cdh_val and cdh_val > price: static_resistances.append(cdh_val)
                                        
                                        # STEP 2: Fetch 5-minute candles for structure analysis
                                        df_risk = fetch_candle_data(dhan, token, symbol, "FIVE_MINUTE")
                                        
                                        if df_risk is None or df_risk.empty:
                                            logger.warning(f"❌ Skipping {symbol}: No data for risk calc")
                                            continue # Don't take trade without risk calculation
                                        
                                        # Calculate indicators (VWAP, EMAs)
                                        df_risk = calculate_indicators(df_risk)
                                        
                                        if len(df_risk) < 2:
                                            logger.warning(f"❌ Skipping {symbol}: Insufficient candle data")
                                            continue
                                        
                                        # Get latest VWAP and EMA20 (Use confirmed candle to avoid repainting)
                                        latest_candle = df_risk.iloc[-2]
                                        vwap = latest_candle.get('VWAP')
                                        ema20 = latest_candle.get('EMA_20')
                                        
                                        if pd.isna(vwap) or pd.isna(ema20):
                                            logger.warning(f"❌ Skipping {symbol}: Missing VWAP or EMA20")
                                            continue
                                        
                                        # Calculate Dynamic Auto-Pivot S/R using the 5M chart
                                        dynamic_resistances = []
                                        dyn_levels = get_dynamic_sr_levels(df_risk)
                                        for level in dyn_levels:
                                            # If pivot zone is acting as resistance above current price
                                            if level['lo'] > price: 
                                                dynamic_resistances.append(level['lo'])
                                                
                                        all_resistances = static_resistances + dynamic_resistances
                                        nearest_res = min(all_resistances) if all_resistances else None
                                        
                                        if nearest_res:
                                            dist_pct = (nearest_res - price) / price * 100
                                            if dist_pct < 0.25:
                                                logger.warning(f"❌ Trade REJECTED: {symbol} | Too close to Resistance (Res: {nearest_res:.2f}, Dist: {dist_pct:.2f}% < 0.25%)")
                                                continue
                                            logger.info(f"✅ S/R Check Pass: Nearest Res {nearest_res:.2f} (Dist: {dist_pct:.2f}%)")
                                        else:
                                            logger.info(f"🚀 Blue Sky Breakout: {symbol} price {price} > All known Resistances")
                                            
                                        # Calculate structure-based SL
                                        sl_price, sl_reason, sl_distance = calculate_structure_based_sl(
                                            df_risk, price, vwap, ema20
                                        )
                                        
                                        if sl_price is None:
                                            logger.warning(f"❌ Trade REJECTED: {symbol} | Reason: {sl_reason}")
                                            continue
                                        
                                        # Rule 2: Reward Space (R:R to Resistance)
                                        # Only applies if there IS a resistance overhead.
                                        if nearest_res:
                                            risk = price - sl_price
                                            reward_space = nearest_res - price
                                            
                                            if risk > 0:
                                                rr_to_res = reward_space / risk
                                                
                                                # New R:R Logic (Refined)
                                                # 1. Strict Reject if < 1.2
                                                if rr_to_res < 1.2:
                                                    logger.warning(f"❌ Trade REJECTED: {symbol} | Low Reward to Res ({rr_to_res:.2f}R < 1.2R)")
                                                    continue
                                                
                                                # 2. Confirmation Zone (1.2 - 1.5)
                                                elif 1.2 <= rr_to_res < 1.5:
                                                    # Require Extra Strength: Volume > 1.8x OR Breakout > CDH
                                                    # Require Extra Strength: Volume > 1.8x OR Breakout > CDH
                                                    current_vol = latest_candle.get('volume', 0)
                                                    avg_vol = latest_candle.get('Volume_SMA_20', 0)
                                                    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0
                                                    
                                                    is_high_vol = vol_ratio > 1.8
                                                    # Check if price broke CDH (Blue Sky) - closest approx using SR levels
                                                    is_breakout = False
                                                    if sr_levels:
                                                        cdh_level = sr_levels.get('CDH', 999999)
                                                        if price > cdh_level:
                                                            is_breakout = True
                                                    
                                                    if is_high_vol or is_breakout:
                                                        logger.info(f"✅ Low R:R Accepted ({rr_to_res:.2f}R) due to Strength: Vol={vol_ratio:.1f}x or Breakout={is_breakout}")
                                                    else:
                                                        logger.warning(f"❌ Trade REJECTED: {symbol} | Low R:R ({rr_to_res:.2f}R) & Weak Confirmation (Vol {vol_ratio:.1f}x < 1.8x, No Breakout)")
                                                        continue
                                                
                                                else:
                                                    logger.info(f"✅ S/R Reward Check Pass: {rr_to_res:.2f}R to Res (> 1.5R)")

                                        # Update PDH for TP calculation (prefer calculated value)
                                        pdh = pdh_val if 'pdh_val' in locals() and pdh_val > 0 else BOT_STATE.get("previous_day_high", {}).get(symbol)
                                        
                                        # Calculate structure-based TP
                                        target_price, tp_reason, rr_ratio = calculate_structure_based_tp(
                                            price, sl_price, df_risk, pdh, dynamic_resistances
                                        )
                                        
                                        if target_price is None:
                                            logger.warning(f"❌ Trade REJECTED: {symbol} | Reason: {tp_reason}")
                                            continue
                                        
                                        logger.info(f"✅ Structure Risk Validated: {symbol}")
                                        logger.info(f"   SL: ₹{sl_price:.2f} | {sl_reason}")
                                        logger.info(f"   TP: ₹{target_price:.2f} | {tp_reason}")
                                    else:
                                        # Fallback to percentage-based (old system)
                                        sl_price = price * (1 - config_manager.get("risk", "stop_loss_pct"))
                                        target_price = price * (1 + config_manager.get("risk", "target_pct"))
                                        logger.info(f"Using percentage-based risk (fallback mode)")
                                    
                                    # === POSITION SIZING ===
                                    sizing_mode = config_manager.get("position_sizing", "mode") or "dynamic"
                                    dry_run = config_manager.get("general", "dry_run")
                                    
                                    if sizing_mode == "dynamic":
                                        # Dynamic position sizing based on account balance and SL
                                        balance = get_account_balance(dhan, dry_run)
                                        risk_pct = config_manager.get("position_sizing", "risk_per_trade_pct") or 1.0
                                        max_pos_pct = config_manager.get("position_sizing", "max_position_size_pct") or 20.0
                                        min_sl_pct = config_manager.get("position_sizing", "min_sl_distance_pct") or 0.6
                                        
                                        quantity = calculate_position_size(
                                            price, sl_price, balance, risk_pct, max_pos_pct, min_sl_pct, symbol
                                        )
                                        
                                        # Safety check: Skip trade if qty is 0 (failed validation)
                                        if quantity <= 0:
                                            logger.warning(f"❌ Trade SKIPPED: {symbol} | Position sizing returned qty=0")
                                            continue
                                            
                                        # New Rule: Min Actual Risk Check
                                        # Actual Risk % = (Qty * SL_Dist_Amt) / Balance
                                        risk_amt = quantity * (price - sl_price)
                                        actual_risk_pct = (risk_amt / balance) * 100 if balance > 0 else 0
                                        
                                        # Threshold: Safety=0.5%, Trend=0.35%
                                        regime = BOT_STATE.get("market_regime", "SAFETY_MODE")
                                        min_risk_threshold = 0.5 if regime == "SAFETY_MODE" else 0.35
                                        
                                        if actual_risk_pct < min_risk_threshold:
                                            logger.warning(f"❌ Trade REJECTED: {symbol} | Actual Risk too low ({actual_risk_pct:.2f}% < {min_risk_threshold}%) - Not worth capital lock.")
                                            continue
                                            
                                        logger.info(f"✅ Risk Check Passed: Actual Risk {actual_risk_pct:.2f}% (>= {min_risk_threshold}%)")
                                    else:
                                        # Fixed quantity mode (backwards compatible)
                                        quantity = config_manager.get("general", "quantity") or 1
                                        logger.info(f"📊 Fixed Quantity Mode: {quantity} shares")
                                    
                                    # Place the order
                                    
                                    # LAST SECOND SAFETY CHECK (Watchdog Race Condition)
                                    if not BOT_STATE.get("is_trading_allowed", True):
                                        logger.warning("🚨 Trading Disabled by Watchdog! Skipping remaining signals.")
                                        break
                                        
                                    correlation_id = generate_correlation_id(symbol, "BUY")
                                    orderId = place_buy_order(dhan, symbol, token, quantity, correlation_id)
                                    
                                    if not orderId:
                                        logger.warning(f"⚠️ Buy Order Skipped (Duplicate or Failed): {symbol} | cID: {correlation_id}")
                                        continue
                                    
                                    # Verify Order Status
                                    if orderId:
                                        is_success, status, avg_price = verify_order_status(dhan, orderId)
                                        
                                        # --- TIMEOUT RECOVERY: LAST RESORT ---
                                        if not is_success and "TIMEOUT" in str(status):
                                            logger.warning(f"⚠️ Order Verification Timed Out for {symbol}. Checking Positions directly...")
                                            from dhan_api_helper import fetch_net_positions
                                            live_positions = fetch_net_positions(dhan)
                                            if live_positions:
                                                for pos in live_positions:
                                                    # Check if symbol matches and qty matches (approx)
                                                    if pos.get("tradingsymbol") == symbol and abs(int(pos.get("netqty", 0))) == quantity:
                                                        logger.info(f"✅ RECOVERY SUCCESS: Found {symbol} in positions! Assuming Order Success.")
                                                        is_success = True
                                                        status = "TRADED (RECOVERED)"
                                                        avg_price = float(pos.get("avgnetprice", 0))
                                                        # If avg_price is 0, use last known price
                                                        if avg_price == 0: avg_price = price
                                                        break
                                        # -------------------------------------
                                        
                                        if is_success:
                                            entry_price = avg_price if avg_price > 0 else price
                                            
                                            with state_lock:
                                                BOT_STATE["positions"][symbol] = {
                                                    "symbol": symbol,
                                                    "entry_price": entry_price,
                                                    "qty": quantity,
                                                    "status": "OPEN",
                                                    "entry_time": get_ist_now().strftime("%H:%M"),
                                                    "entry_time_ts": get_ist_now().timestamp(),
                                                    "sl": sl_price,
                                                    "target": target_price,
                                                    "original_sl": sl_price,
                                                    "highest_ltp": entry_price,
                                                    "is_breakeven_active": False,
                                                    "order_id": orderId
                                                }
                                                BOT_STATE["total_trades_today"] += 1
                                                
                                                # Update specific stock count
                                                BOT_STATE["stock_trade_counts"][symbol] = BOT_STATE["stock_trade_counts"].get(symbol, 0) + 1
                                                
                                            save_state(BOT_STATE) 
                                            broadcast_state() 
                                            logger.info(f"✅ Trade Confirmed: {symbol} @ {entry_price}")
                                        else:
                                            logger.error(f"❌ Trade Rejected/Failed Validation: {symbol} Status: {status}")
                                    else:
                                        logger.error(f"❌ Failed to place order for {symbol}")
                # ---------------------------- 
                
                # BROADCAST END of Cycle
                broadcast_state()
                
                # Dynamic Interval: Market Movers need faster updates
                effective_interval = config_manager.get("general", "check_interval") or 300
                if strategy_mode == "MARKET_MOVER":
                    effective_interval = 60 # 1 minute for fast-moving ranks
                    logger.info(f"⚡ Market Mode: Using faster scan interval (60s).")
                
                logger.info(f"Cycle Complete. Sleeping {effective_interval}s...")
                time.sleep(effective_interval)
    
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in Main Loop: {e}")
                print(f"CRITICAL ERROR IN MAIN LOOP: {e}") # Force stdout
                import traceback
                traceback.print_exc()
                time.sleep(60)
        
    except Exception as e:
        logger.critical(f"Critical Bot Loop Crash: {e}", exc_info=True)
        time.sleep(10)
    BOT_STATE["is_running"] = False

if __name__ == "__main__":
    run_bot_loop()
