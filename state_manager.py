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
        "stock_trade_counts": {}
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

def start_auto_save(state, interval=10):
    """
    Starts a background thread to auto-save state periodically.
    """
    def loop():
        while True:
            time.sleep(interval)
            save_state(state)
            
    t = threading.Thread(target=loop, daemon=True)
    t.start()
