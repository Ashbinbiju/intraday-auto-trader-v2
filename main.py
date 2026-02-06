import logging
import time
import sys
import asyncio
import pandas as pd
import threading # Added for log_trade_to_db
from scraper import fetch_top_performing_sectors, fetch_stocks_in_sector, fetch_market_indices
from dhan_api_helper import get_dhan_session, load_dhan_instrument_map, fetch_candle_data, fetch_ltp, fetch_net_positions, place_order_api, fetch_holdings
from indicators import calculate_indicators, check_buy_condition
from utils import is_market_open, get_ist_now
from config import config_manager
from state_manager import load_state, save_state, start_auto_save, state_lock
from database import log_trade_to_db
from async_scanner import AsyncScanner

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
                
                # Keep only last 100 logs (Prevent Bloat)
                if len(BOT_STATE["logs"]) > 100:
                    BOT_STATE["logs"] = BOT_STATE["logs"][-100:]
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

def place_buy_order(smartApi, symbol, token, qty):
    """
    Places a Buy Order.
    """
    dry_run = config_manager.get("general", "dry_run")
    if dry_run:
        logger.info(f"[DRY RUN] Simulated BUY Order Placed for {symbol} | Qty: {qty}")
        return True

    try:
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": f"{symbol}-EQ",
            "symboltoken": token,
            "transactiontype": "BUY",
            "exchange": "NSE",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "quantity": qty
        }
        orderId = smartApi.placeOrder(orderparams)
        logger.info(f"Order Placed for {symbol} | Order ID: {orderId}")
        return orderId
    except Exception as e:
        logger.error(f"Order Placement Failed for {symbol}: {e}")
        return None

# Shared State for API
SMART_API_SESSION = None
TOKEN_MAP = {}



def place_sell_order(smartApi, symbol, token, qty, reason="EXIT"):
    """
    Places a Sell Order to exit a position.
    """
    dry_run = config_manager.get("general", "dry_run")
    if dry_run:
        logger.info(f"[DRY RUN] Simulated SELL for {symbol} | Reason: {reason} | Qty: {qty}")
        return True

    try:
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": f"{symbol}-EQ",
            "symboltoken": token,
            "transactiontype": "SELL",
            "exchange": "NSE",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "quantity": qty
        }
        orderId = smartApi.placeOrder(orderparams)
        logger.info(f"SELL Order Placed for {symbol} ({reason}) | Order ID: {orderId}")
        return orderId
    except Exception as e:
        logger.error(f"SELL Order Failed for {symbol}: {e}")
        return None

def get_account_balance(smartApi, dry_run):
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
        rmsLimit = smartApi.rmsLimit()
        if rmsLimit and 'data' in rmsLimit:
            available_balance = rmsLimit['data'].get('availablecash', 0)
            logger.info(f"📊 [LIVE] Account balance fetched: ₹{float(available_balance):,.0f}")
            return float(available_balance)
        else:
            logger.warning("Unable to fetch balance, using fallback: ₹100,000")
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
    return max(1, int(qty))

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
    # 🔴 FIX 1: Zero SL distance protection
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        logger.warning(f"❌ {symbol}: Invalid SL distance (Entry={entry_price}, SL={sl_price}), skipping trade")
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
    max_qty = int((balance * max_position_pct / 100) / entry_price)
    qty = min(qty, max_qty)
    
    # 🟠 FIX 2: Lot size rounding
    qty = floor_to_lot_size(qty, symbol)
    
    # Ensure at least 1 share (if we got this far)
    if qty <= 0:
        logger.warning(f"❌ {symbol}: Calculated qty={qty}, skipping trade")
        return 0
    
    # Calculate actual exposure and risk
    exposure = qty * entry_price
    actual_risk = qty * sl_distance
    exposure_pct = (exposure / balance) * 100
    actual_risk_pct = (actual_risk / balance) * 100
    
    # 4️⃣ FIX 5: Comprehensive logging
    logger.info(
        f"📊 Position Sizing | {symbol} | "
        f"Bal=₹{balance:,.0f} | Risk={risk_pct}% (₹{risk_amount:,.0f}) | "
        f"SL={sl_distance:.2f} ({sl_distance_pct:.2f}%) | "
        f"Qty={qty} | Exposure=₹{exposure:,.0f} ({exposure_pct:.1f}%) | "
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
    
    # Choose by priority FIRST, then by price (closest)
    best_sl, reason = max(valid_candidates, key=lambda x: (priority[x[1]], x[0]))
    
    # Calculate distance
    sl_distance_pct = ((entry_price - best_sl) / entry_price) * 100
    
    # Safety Check: Reject if SL < 0.8% (wick risk)
    if sl_distance_pct < min_sl_distance:
        return None, f"SL too tight ({sl_distance_pct:.2f}%) - wick risk", sl_distance_pct
    
    # Safety Check: Reject if SL > 2% away
    if sl_distance_pct > max_sl_distance:
        return None, f"SL too wide ({sl_distance_pct:.2f}%)", sl_distance_pct
    
    return best_sl, f"{reason} ({sl_distance_pct:.2f}%)", sl_distance_pct


def calculate_structure_based_tp(entry_price, sl_price, df, previous_day_high=None):
    """
    Calculate Take-Profit based on market structure.
    Priority: PDH > Swing High > 1.5R minimum.
    
    Returns: (tp_price, tp_reason, risk_reward_ratio) or (None, reason, 0)
    """
    min_rr = config_manager.get("structure_risk", "min_risk_reward") or 1.5
    
    risk = entry_price - sl_price
    min_reward = risk * min_rr  # Minimum 1.5R
    min_tp = entry_price + min_reward
    
    candidates = []
    
    # Option 1: Previous Day High (if available and above entry)
    if previous_day_high and previous_day_high > entry_price:
        candidates.append((previous_day_high, "PDH"))
    
    # Option 2: Nearest Swing High (last 20 candles)
    recent_candles = df.iloc[-20:]
    swing_high = recent_candles['high'].max()
    
    # Distance filter: Reject swing highs too close (< 0.6%)
    if swing_high > entry_price:
        distance_pct = ((swing_high - entry_price) / entry_price) * 100
        if distance_pct >= 0.6:  # Minimum 0.6% away to avoid front-running
            candidates.append((swing_high, "Swing High"))
    
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


def manage_positions(smartApi, token_map):
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
                ltp_data = smartApi.ltpData("NSE", f"{symbol}-EQ", token)
                exit_price = 0
                
                if ltp_data and 'data' in ltp_data:
                    exit_price = ltp_data['data']['ltp']
                else:
                    logger.warning(f"Could not fetch LTP for TIME_EXIT. Using 0.")
                
                with state_lock:
                    pos = BOT_STATE["positions"].get(symbol)
                    if pos and pos["status"] == "OPEN":
                        place_sell_order(smartApi, symbol, token, pos['qty'], reason="TIME_EXIT")
                        pos['status'] = "CLOSED"
                        pos['exit_price'] = exit_price  # Actual market price
                        pos['exit_reason'] = "TIME_EXIT"
                        
                        # LOG TO SUPABASE
                        trade_log = pos.copy()
                        trade_log['pnl'] = (exit_price - pos['entry_price']) * pos['qty']
                        trade_log['exit_time'] = datetime.datetime.now().isoformat()
                        threading.Thread(target=log_trade_to_db, args=(trade_log,)).start()

                        save_state(BOT_STATE)
                continue

            params = {
                "exchange": "NSE",
                "tradingsymbol": f"{symbol}-EQ",
                "symboltoken": token
            }
            # THROTTLING: Limit to 5 requests/second (Limit is 10/s)
            time.sleep(0.2)
            data = smartApi.ltpData("NSE", f"{symbol}-EQ", token)
            
            if data and 'data' in data:
                current_ltp = data['data']['ltp']
            else:
                logger.warning(f"Could not fetch LTP for {symbol}")
                continue

            # ... (Rest of existing logic) ...
            with state_lock:
                pos = BOT_STATE["positions"].get(symbol)
                
                # Check if still valid and OPEN (might have been closed by API/User)
                if not pos or pos["status"] != "OPEN":
                    continue

                entry_price = pos['entry_price']
                sl_price = pos['sl']
                # target_price = pos['target'] # DISABLED Fixed Target
                
                # UPDATE HIGHEST LTP (For Trailing/Breakeven)
                pos['current_ltp'] = current_ltp  # Store current price for frontend display
                if current_ltp > pos.get('highest_ltp', 0):
                    pos['highest_ltp'] = current_ltp

                # ------------------- EXIT LOGIC PRIORITY -------------------
                # 1. HARD STOP LOSS (Safety Net)
                if current_ltp <= sl_price:
                    logger.info(f"{symbol} Hit STOP LOSS at {current_ltp} (SL: {sl_price})")
                    place_sell_order(smartApi, symbol, token, pos['qty'], reason="STOP LOSS")
                    pos['status'] = "CLOSED"
                    pos['exit_price'] = current_ltp
                    pos['exit_reason'] = "STOP_LOSS"
                    
                    # LOG TO SUPABASE
                    trade_log = pos.copy()
                    trade_log['pnl'] = (current_ltp - entry_price) * pos['qty']
                    trade_log['exit_time'] = datetime.datetime.now().isoformat()
                    threading.Thread(target=log_trade_to_db, args=(trade_log,)).start()

                    save_state(BOT_STATE) 
                    continue

                # 1.5 BREAKEVEN LOCK (Enhancement)
                # If Price moved +1R (Risk), Move SL to Entry
                original_sl = pos.get('original_sl', sl_price)
                risk_per_share = entry_price - original_sl
                if risk_per_share > 0 and not pos.get('is_breakeven_active'):
                    target_move = entry_price + risk_per_share # +1R
                    if pos['highest_ltp'] >= target_move:
                        logger.info(f"🔒 Breakeven Triggered for {symbol}. Moving SL to {entry_price}")
                        pos['sl'] = entry_price * 1.001 # Slightly above to cover brokerage
                        pos['is_breakeven_active'] = True
                        save_state(BOT_STATE)
                        # We don't continue, checks proceed with new SL

                # 2. TRAILING TECHNICAL EXIT (Strict Candle Close)
                # Rule: Exit if Closed Price < EMA20 AND Closed Price < VWAP (Dual Confirmation)
                try:
                    df_tech = fetch_candle_data(smartApi, token, symbol, "FIVE_MINUTE")
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
                                exit_reason = f"Dual Breakdown (Close {close_price} < EMA {ema_20:.2f} & VWAP {vwap:.2f})"
                                logger.info(f"📉 {symbol} Technical Exit: {exit_reason}.")
                                place_sell_order(smartApi, symbol, token, pos['qty'], reason="TECH_EXIT")
                                pos['status'] = "CLOSED"
                                pos['exit_price'] = current_ltp 
                                pos['exit_reason'] = "TECH_EXIT"
                                
                                # LOG TO SUPABASE
                                trade_log = pos.copy()
                                trade_log['pnl'] = (current_ltp - entry_price) * pos['qty']
                                trade_log['exit_time'] = datetime.datetime.now().isoformat()
                                threading.Thread(target=log_trade_to_db, args=(trade_log,)).start()

                                save_state(BOT_STATE)
                                continue

                except Exception as e_tech:
                     logger.warning(f"Technical Exit Check failed for {symbol}: {e_tech}")

                # 3. TIME-BASED STAGNATION EXIT (Intraday Reality)
                # If Trade > 60 mins AND Profit < 0.5% -> Exit
                # This frees up capital from zombie trades.
                entry_ts = pos.get('entry_time_ts')
                if entry_ts:
                    duration_seconds = time.time() - entry_ts
                    duration_minutes = duration_seconds / 60
                    current_profit_pct = (current_ltp - entry_price) / entry_price
                    
                    if duration_minutes > 60 and current_profit_pct < 0.005: # < 0.5% gain after 1 hour
                        logger.info(f"💤 Time Exit: {symbol} Stagnant for {int(duration_minutes)}m. Closing.")
                        place_sell_order(smartApi, symbol, token, pos['qty'], reason="TIME_EXIT")
                        pos['status'] = "CLOSED"
                        pos['exit_price'] = current_ltp 
                        pos['exit_reason'] = "TIME_EXIT"
                        
                        # LOG TO SUPABASE
                        trade_log = pos.copy()
                        trade_log['pnl'] = (current_ltp - entry_price) * pos['qty']
                        trade_log['exit_time'] = datetime.datetime.now().isoformat()
                        threading.Thread(target=log_trade_to_db, args=(trade_log,)).start()

                        save_state(BOT_STATE)
                        continue


        except Exception as e:
            logger.error(f"Error managing position {symbol}: {e}")

def reconcile_state(smartApi):
    """
    Syncs BOT_STATE with Broker's Live Positions.
    Broker is the SOURCE OF TRUTH.
    Thread-Safe.
    """
    logger.info("Starting Startup Reconciliation...")
    try:
        live_positions = fetch_net_positions(smartApi)
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

import asyncio

# ... imports ...

def run_bot_loop(async_loop=None, ws_manager=None):
    """
    Background task to run the bot loop.
    Accepts async_loop and ws_manager to broadcast updates via WebSockets.
    """
    global BOT_STATE, SMART_API_SESSION, TOKEN_MAP
    BOT_STATE["is_running"] = True
    
    logger.info("Starting Auto Buy/Sell Bot...")

    # Helper to broadcast updates
    def broadcast_state():
        if async_loop and ws_manager:
            try:
                # We send the entire BOT_STATE. For optimization, we could send diffs.
                # Use run_coroutine_threadsafe to bridge Sync Thread -> Async Loop
                asyncio.run_coroutine_threadsafe(ws_manager.broadcast(BOT_STATE), async_loop)
            except Exception as e:
                logger.error(f"WS Broadcast Failed: {e}")

    # ... (SmartAPI Init) ...
    # 1. Initialize Dhan API
    dhan = get_dhan_session()
    if not dhan:
        logger.critical("Failed to connect to Dhan API. Exiting.")
        BOT_STATE["is_running"] = False
        return
    
    SMART_API_SESSION = dhan # Keeping variable name for compatibility with rest of code logic (for now)
    smartApi = dhan 

    # 2. Load Dhan Instrument Map
    token_map = load_dhan_instrument_map()
    if not token_map:
        logger.critical("Failed to load Dhan Token Map. Exiting.")
        BOT_STATE["is_running"] = False
        return
        
    TOKEN_MAP = token_map

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
                    time.sleep(1800) 
                    # Still broadcast while sleeping occasionally?
                    continue
                # -----------------------------
                
                # ... (Rest of logic) ...
                
                # --- Reconciliation (Only in Live Mode) ---
                dry_run = config_manager.get("general", "dry_run") or False
                if SMART_API_SESSION and not dry_run:
                     success = reconcile_state(SMART_API_SESSION)
                     if not success:
                         logger.warning("Reconciliation Failed. Attempting to Re-Authenticate...")
                         new_session = get_dhan_session()
                         if new_session:
                             SMART_API_SESSION = new_session
                             smartApi = new_session # Update local reference
                             logger.info("Session Re-established successfully. ✅")
                         else:
                             logger.error("Session Re-authentication Failed. Will retry next cycle.")
                elif dry_run:
                    logger.debug("Dry-Run Mode: Skipping reconciliation with broker.")
                # ----------------------
                
                # --- Daily Signal Reset ---
                from state_manager import check_and_reset_daily_signals
                check_and_reset_daily_signals(BOT_STATE)
                # --------------------------
    
                # --- Manage Active Positions ---
                manage_positions(smartApi, token_map)
                # -------------------------------
                
                # BROADCAST AFTER MANAGEMENT (Price updates, exits)
                broadcast_state()
    
                # ... (Trade Guards) ...
                trading_end_time = config_manager.get("limits", "trading_end_time")
                trading_start_time = config_manager.get("limits", "trading_start_time") or "09:30"
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
    
                if current_time < trading_start_time:
                    logger.info(f"Market Open, but waiting for Strategy Start Time ({trading_start_time})...")
                    time.sleep(60)
                    continue
    
                if current_time >= trading_end_time:
                    time.sleep(60) 
                    continue
    
                if BOT_STATE["total_trades_today"] >= max_trades_day:
                    time.sleep(60)
                    continue
    
                # --- Fetch Market Indices (New) ---
                indices = fetch_market_indices()
                if indices:
                    BOT_STATE["indices"] = indices
                    broadcast_state() # Update UI with indices
                # ----------------------------------
                
                # ... (Scanning) ...
                sectors = fetch_top_performing_sectors()
                    
                # ... (Scanning) ...
                sectors = fetch_top_performing_sectors()
                if sectors:
                     logger.info(f"DEBUG: Main Loop Scraped {len(sectors)} sectors. Top: {[s['name'] for s in sectors[:4]]}")

                if not sectors:
                    logger.info("No sector data available. Skipping scan. 📉")
                    pass
                
                target_sectors = sectors[:4] if sectors else []
                BOT_STATE["top_sectors"] = target_sectors
    
                stocks_to_scan = []
                seen_symbols = set()
                
                for sector in target_sectors:
                    # ... check stocks ...
                    stocks = fetch_stocks_in_sector(sector['key'])
                    for stock in stocks:
                        symbol = stock['symbol']
                        
                        # Dedup
                        if symbol in seen_symbols: continue
                        seen_symbols.add(symbol)
                        
                        # Skip if Position Open
                        if symbol in BOT_STATE["positions"] and BOT_STATE["positions"][symbol]["status"] == "OPEN":
                            continue
                            
                        # Skip if Stock limits hit
                        current_stock_trades = BOT_STATE["stock_trade_counts"].get(symbol, 0)
                        if current_stock_trades >= max_trades_stock:
                            continue
                        
                        # Prepare for Async Scan
                        stock['sector'] = sector['name']
                        stocks_to_scan.append(stock)
    
                if BOT_STATE["total_trades_today"] >= max_trades_day:
                    time.sleep(60)
                    continue
    
                # -- ASYNC BATCH SCAN --
                if stocks_to_scan:
                    # Initialize Scanner with fresh SmartAPI Session Object
                    # Legacy: Pass token. New: Pass smartApi object for robustness.
                    scanner = AsyncScanner("UNUSED_TOKEN", smartApi=smartApi)
                    
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
                                        df_15m_recheck = fetch_candle_data(smartApi, token, symbol, "FIFTEEN_MINUTE")
                                        
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
                                        
                                        # STEP 2: Fetch 5-minute candles for structure analysis
                                        df_risk = fetch_candle_data(smartApi, token, symbol, "FIVE_MINUTE")
                                        
                                        if df_risk is None or df_risk.empty:
                                            logger.warning(f"❌ Skipping {symbol}: No data for risk calc")
                                            continue # Don't take trade without risk calculation
                                        
                                        # Calculate indicators (VWAP, EMAs)
                                        df_risk = calculate_indicators(df_risk)
                                        
                                        if len(df_risk) < 2:
                                            logger.warning(f"❌ Skipping {symbol}: Insufficient candle data")
                                            continue
                                        
                                        # Get latest VWAP and EMA20
                                        latest_candle = df_risk.iloc[-1]
                                        vwap = latest_candle.get('VWAP')
                                        ema20 = latest_candle.get('EMA_20')
                                        
                                        if pd.isna(vwap) or pd.isna(ema20):
                                            logger.warning(f"❌ Skipping {symbol}: Missing VWAP or EMA20")
                                            continue
                                        
                                        # Calculate structure-based SL
                                        sl_price, sl_reason, sl_distance = calculate_structure_based_sl(
                                            df_risk, price, vwap, ema20
                                        )
                                        
                                        if sl_price is None:
                                            logger.warning(f"❌ Trade REJECTED: {symbol} | Reason: {sl_reason}")
                                            continue
                                        
                                        # Get PDH from bot state (if available)
                                        pdh = BOT_STATE.get("previous_day_high", {}).get(symbol)
                                        
                                        # Calculate structure-based TP
                                        target_price, tp_reason, rr_ratio = calculate_structure_based_tp(
                                            price, sl_price, df_risk, pdh
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
                                        balance = get_account_balance(smartApi, dry_run)
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
                                    else:
                                        # Fixed quantity mode (backwards compatible)
                                        quantity = config_manager.get("general", "quantity") or 1
                                        logger.info(f"📊 Fixed Quantity Mode: {quantity} shares")
                                    
                                    # Place the order
                                    orderId = place_buy_order(smartApi, symbol, token, quantity)
                                    
                                    # Verify Order Status
                                    if orderId:
                                        is_success, status, avg_price = verify_order_status(smartApi, orderId)
                                        
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
                                                BOT_STATE["stock_trade_counts"][symbol] = current_stock_trades + 1 # Note: Might be stale? No, loop updates local var, but BOT_STATE is single source
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
                logger.info(f"Cycle Complete. Sleeping...")
                time.sleep(check_interval)
    
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in Main Loop: {e}")
                time.sleep(60)
        
    except Exception as e:
        logger.critical(f"Critical Bot Loop Crash: {e}", exc_info=True)
        time.sleep(10)
    BOT_STATE["is_running"] = False

if __name__ == "__main__":
    run_bot_loop()
