import json
import os
import logging
import threading
import time
from database import get_remote_state, save_remote_state

STATE_FILE = "bot_state.json"
logger = logging.getLogger(__name__)

# Global Lock for BOT_STATE access
state_lock = threading.RLock()

def load_state():
    """
    Loads BOT_STATE from Supabase (priority) or disk (fallback).
    """
    default_state = {
        "status": "IDLE",
        "signals": [],
        "positions": {},
        "orders": {},
        "logs": [],
        "is_trading_allowed": True,
        "limits": {},
        "indices": [],
        "top_sectors": [],
        "total_trades_today": 0,
        "stock_trade_counts": {},
        "last_reset_date": "" # Track the last reset date
    }
    
    # Try loading from Supabase first
    remote_state = get_remote_state()
    if remote_state:
        logger.info("✅ BOT_STATE Loaded from Supabase")
        return remote_state

    # Fallback to Local File
    with state_lock:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    saved_state = json.load(f)
                    
                    # Merge with default to ensure all keys exist
                    for k, v in default_state.items():
                        if k not in saved_state:
                            saved_state[k] = v
                            
                    logger.info("BOT_STATE Loaded from Disk (Local) ✅")
                    return saved_state
            except Exception as e:
                logger.error(f"Failed to load persistence file: {e}. Starting fresh.")
                return default_state
        else:
            logger.info("No persistence file found. Starting fresh.")
            return default_state

def save_state(state):
    """
    Saves BOT_STATE to Supabase and disk.
    Should be called after critical updates.
    """
    try:
        with state_lock:
            # 1. Save to Local Disk (Backup/Fast Access)
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=4)
            
            # 2. Save to Supabase (Async/Background ideally, but sync for safety now)
            save_remote_state(state)
            
    except Exception as e:
        logger.error(f"Error saving state: {e}")

def start_auto_save(state, interval=60):
    """
    Starts a background thread to auto-save state periodically.
    Default: Every 60 seconds (reduced from 10s to minimize log spam)
    """
    def loop():
        while True:
            time.sleep(interval)
            save_state(state)
            
    t = threading.Thread(target=loop, daemon=True)
    t.start()


def check_and_reset_daily_signals(state):
    """
    Clears signals, trade counts, and yesterday's closed positions if it's a new trading day.
    Uses 'last_reset_date' to track when the last reset occurred.
    """
    from datetime import datetime
    import logging
    logger = logging.getLogger(__name__)
    
    with state_lock:
        current_date_str = datetime.now().strftime("%Y-%m-%d")
        last_reset = state.get("last_reset_date", "")
        
        # Check if reset is needed (last_reset is empty OR last_reset is before today)
        needs_reset = False
        if not last_reset:
            needs_reset = True
        else:
            if current_date_str > last_reset:
                needs_reset = True
        
        if needs_reset:
            logger.info(f"🔄 Daily Reset Triggered! (Current: {current_date_str}, Last: {last_reset})")
            
            # 1. Reset Counters
            state["total_trades_today"] = 0
            state["stock_trade_counts"] = {}
            state["signals"] = [] # Clear daily signals
            
            # 2. Clear CLOSED positions from previous days
            # (Keep OPEN positions intact)
            positions = state.get("positions", {})
            positions_to_remove = []
            
            for symbol, pos in positions.items():
                if pos.get("status") == "CLOSED":
                    # We can aggressively remove ALL closed positions on reset
                    # OR carefully remove only old ones. 
                    # Aggressive is cleaner for "Daily Reset".
                    positions_to_remove.append(symbol)
                elif pos.get("status") == "OPEN":
                    logger.info(f"⚠️ Keeping OPEN position {symbol} during daily reset.")

            if positions_to_remove:
                logger.info(f"🗑️ Clearing {len(positions_to_remove)} closed positions.")
                for symbol in positions_to_remove:
                    del state["positions"][symbol]
            
            # 3. Update Reset Date
            state["last_reset_date"] = current_date_str
            save_state(state)
            logger.info("✅ Daily Reset Completed & Saved.")
        else:
            # Already reset for today or future date (unlikely)
            pass
