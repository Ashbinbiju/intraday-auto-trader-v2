import os
import json
import logging
from supabase import create_client, Client
from datetime import datetime

# Setup Logger
logger = logging.getLogger(__name__)

# Supabase Credentials (Provided by User)
SUPABASE_URL = "https://dikpaqjfmbphkssfecgg.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRpa3BhcWpmbWJwaGtzc2ZlY2dnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njk5Mzc4MzgsImV4cCI6MjA4NTUxMzgzOH0.a-RW7asIZQyG3YbxpT720SosQJofx5wJumYg-q812Ik"

# Initialize Supabase Client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✅ Supabase Client Initialized")
except Exception as e:
    logger.error(f"❌ Failed to initialize Supabase: {e}")
    supabase = None

# --- Configuration (Settings) ---

def get_remote_config():
    """Fetches config.json from Supabase."""
    if not supabase: return None
    try:
        response = supabase.table("bot_config").select("data").eq("id", "global").execute()
        if response.data and len(response.data) > 0:
            logger.info("✅ Loaded Config from Supabase")
            return response.data[0]['data']
        return None
    except Exception as e:
        logger.error(f"❌ Error fetching remote config: {e}")
        return None

def save_remote_config(config_data):
    """Saves config.json to Supabase."""
    if not supabase: return
    try:
        data = {"id": "global", "data": config_data, "updated_at": datetime.utcnow().isoformat()}
        supabase.table("bot_config").upsert(data).execute()
        logger.info("✅ Saved Config to Supabase")
    except Exception as e:
        logger.error(f"❌ Error saving remote config: {e}")

# --- Bot State (Active Positions) ---

def get_remote_state():
    """Fetches bot_state.json from Supabase."""
    if not supabase: return None
    try:
        response = supabase.table("bot_state").select("data").eq("id", "global").execute()
        if response.data and len(response.data) > 0:
            logger.info("✅ Loaded Bot State from Supabase")
            return response.data[0]['data']
        return None
    except Exception as e:
        logger.error(f"❌ Error fetching remote state: {e}")
        return None

def save_remote_state(state_data):
    """Saves bot_state.json to Supabase."""
    if not supabase: return
    try:
        data = {"id": "global", "data": state_data, "updated_at": datetime.utcnow().isoformat()}
        supabase.table("bot_state").upsert(data).execute()
        # Debug log removed to prevent spam, un-comment if needed
        # logger.info("✅ Saved State to Supabase") 
    except Exception as e:
        logger.error(f"❌ Error saving remote state: {e}")

# --- Trade History (Logs) ---

def log_trade_to_db(trade_data):
    """Logs a completed trade to the trade_history table."""
    if not supabase: return
    try:
        # Map fields to match SQL schema
        record = {
            "symbol": trade_data.get("symbol"),
            "entry_price": trade_data.get("entry_price"),
            "exit_price": trade_data.get("exit_price"),
            "qty": trade_data.get("qty"),
            "pnl": trade_data.get("pnl"),
            "status": trade_data.get("status", "CLOSED"),
            "entry_time": trade_data.get("entry_time"), # Ensure ISO format or compatible
            "exit_time": trade_data.get("exit_time"),
            "metadata": json.dumps(trade_data) # Store raw extra data
        }
        supabase.table("trade_history").insert(record).execute()
        logger.info(f"✅ Trade Logged to DB: {trade_data.get('symbol')}")
    except Exception as e:
        logger.error(f"❌ Error logging trade to DB: {e}")

# --- Market Data (Movers) ---

def log_market_movers_to_db(movers_data):
    """
    Logs the list of market movers to the 'market_movers' table.
    Expects a list of dicts: [{'symbol': 'X', 'rank': 1, 'ltp': 100, 'change': 5.5, ...}]
    """
    if not supabase: return
    try:
        timestamp = datetime.utcnow().isoformat()
        records = []
        
        for m in movers_data:
            records.append({
                "timestamp": timestamp,
                "symbol": m.get("symbol"),
                "rank": m.get("rank"),
                "ltp": float(m.get("ltp", 0)),
                "change": float(m.get("change", 0)),
                "side": "Gainer" # Currently we only fetch Gainers
            })
            
        if records:
            supabase.table("market_movers").insert(records).execute()
            logger.info(f"✅ Logged {len(records)} Market Movers to DB")
            
    except Exception as e:
        logger.error(f"❌ Error logging market movers to DB: {e}")
