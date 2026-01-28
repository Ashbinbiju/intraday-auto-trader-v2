import logging
import time
import sys
import asyncio
from scraper import fetch_top_performing_sectors, fetch_stocks_in_sector, fetch_market_indices
from smart_api_helper import get_smartapi_session, fetch_candle_data, load_instrument_map, fetch_net_positions, verify_order_status
from indicators import calculate_indicators, check_buy_condition
from utils import is_market_open, get_ist_now
from config import config_manager
from state_manager import load_state, save_state, start_auto_save, state_lock
from async_scanner import AsyncScanner

# Configure Logging
import datetime

def ist_converter(*args):
    utc_dt = datetime.datetime.now(datetime.timezone.utc)
    ist_dt = utc_dt + datetime.timedelta(hours=5, minutes=30)
    return ist_dt.timetuple()

class LogBufferHandler(logging.Handler):
    def emit(self, record):
        try:
            log_entry = self.format(record)
            # Append to global shared buffer
            if "BOT_STATE" in globals():
                if len(BOT_STATE["logs"]) > 100:
                    BOT_STATE["logs"].pop(0)
                BOT_STATE["logs"].append(log_entry)
        except Exception:
            self.handleError(record)

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

logger = logging.getLogger("MainBot")

# --- GLOBAL STATE INITIALIZATION ---
# Load state from disk or use default
BOT_STATE = load_state()

# Start background auto-save (every 10s)
start_auto_save(BOT_STATE, interval=10)
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
            # 0. Check Auto Square-Off Time (User Requested 14:45)
            # Was 15:15, now strict 14:45 Exit
            if current_time >= "14:45":
                logger.info(f"⏰ Time Limit Reached (14:45). Booking Profit/Loss for {symbol}...")
                with state_lock:
                    pos = BOT_STATE["positions"].get(symbol)
                    if pos and pos["status"] == "OPEN":
                        place_sell_order(smartApi, symbol, token, pos['qty'], reason="TIME_EXIT")
                        pos['status'] = "CLOSED"
                        pos['exit_price'] = 0 # Market Exit
                        pos['exit_reason'] = "TIME_EXIT"
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
                    df_tech = fetch_candle_data(smartApi, token, symbol, "FIFTEEN_MINUTE")
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
                        save_state(BOT_STATE)
                        continue

                except Exception as e_tech:
                     logger.warning(f"Technical Exit Check failed for {symbol}: {e_tech}")

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
    # 1. Initialize SmartAPI
    smartApi = get_smartapi_session()
    if not smartApi:
        logger.critical("Failed to connect to SmartAPI. Exiting.")
        BOT_STATE["is_running"] = False
        return
    
    SMART_API_SESSION = smartApi 

    # 2. Load Instrument Map
    token_map = load_instrument_map()
    if not token_map:
        logger.critical("Failed to load Token Map. Exiting.")
        BOT_STATE["is_running"] = False
        return
        
    TOKEN_MAP = token_map

    while True:
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
            
            # --- Reconciliation ---
            if SMART_API_SESSION:
                 success = reconcile_state(SMART_API_SESSION)
                 if not success:
                     logger.warning("Reconciliation Failed. Attempting to Re-Authenticate...")
                     new_session = get_smartapi_session()
                     if new_session:
                         SMART_API_SESSION = new_session
                         smartApi = new_session # Update local reference
                         logger.info("Session Re-established successfully. ✅")
                     else:
                         logger.error("Session Re-authentication Failed. Will retry next cycle.")
            # ----------------------

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
            if not sectors:
                logger.info("No positive performing sectors found. Skipping scan. 📉")
                # Broaden search or just wait? For now, wait.
                pass
            
            target_sectors = sectors[:2] if sectors else []
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

            # --- ASYNC BATCH SCAN ---
            if stocks_to_scan:
                # Initialize Scanner with fresh token
                scanner = AsyncScanner(smartApi.jwt_token)
                
                # Run Async Scan (Blocking Call)
                # Ensure we pass the Token Map for lookup
                signals = asyncio.run(scanner.scan(stocks_to_scan, token_map))
                
                # Process Signals Sequentially (Trade Execution is Sync/Sensitive)
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

                    # --- AUTO BUY LOGIC (Reused) ---
                    if message.startswith("Strong Buy"):
                        current_trades = len([p for p in BOT_STATE["positions"].values() if p["status"] == "OPEN"])
                        if current_trades < max_trades_day:
                            logger.info(f"🚀 Executing BUY for {symbol} at {price}")
                            
                            token = token_map.get(symbol)
                            if token:
                                orderId = place_buy_order(smartApi, symbol, token, quantity)
                                
                                # Verify Order Status
                                if orderId:
                                    is_success, status, avg_price = verify_order_status(smartApi, orderId)
                                    
                                    if is_success:
                                        entry_price = avg_price if avg_price > 0 else price
                                        
                                        with state_lock:
                                            sl_price = entry_price * (1 - config_manager.get("risk", "stop_loss_pct"))
                                            BOT_STATE["positions"][symbol] = {
                                                "symbol": symbol,
                                                "entry_price": entry_price,
                                                "qty": quantity,
                                                "status": "OPEN",
                                                "entry_time": get_ist_now().strftime("%H:%M"),
                                                "entry_time_ts": get_ist_now().timestamp(), # Added for Time Exit
                                                "sl": sl_price,
                                                "original_sl": sl_price, # Added for Breakeven Calculation (R)
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
    
    BOT_STATE["is_running"] = False

if __name__ == "__main__":
    run_bot_loop()
