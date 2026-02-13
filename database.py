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
        current_time = datetime.now().isoformat()
        
        # Validate and Format format 'entry_time'
        entry_time = trade_data.get("entry_time")
        if not entry_time or "RECONCILED" in str(entry_time) or "UNKNOWN" in str(entry_time):
             entry_time = current_time # Default to NOW if invalid
        elif len(str(entry_time)) <= 8: # Likely "10:51" or "10:51:00"
             today_date = datetime.now().date().isoformat()
             entry_time = f"{today_date}T{entry_time}:00"
             
        # Validate 'exit_time' similarly
        exit_time = trade_data.get("exit_time")
        if not exit_time or "RECONCILED" in str(exit_time):
             exit_time = current_time
        
        # Map fields to match SQL schema
        record = {
            "symbol": trade_data.get("symbol"),
            "entry_price": trade_data.get("entry_price"),
            "exit_price": trade_data.get("exit_price"),
            "qty": trade_data.get("qty"),
            "pnl": trade_data.get("pnl"),
            "status": trade_data.get("status", "CLOSED"),
            "entry_time": entry_time,
            "exit_time": exit_time,
            "metadata": json.dumps(trade_data) # Store raw extra data
        }
        supabase.table("trade_history").insert(record).execute()
        logger.info(f"✅ Trade Logged to DB: {trade_data.get('symbol')}")
    except Exception as e:
        logger.error(f"❌ Error logging trade to DB: {e}")

def fetch_trade_history(limit=1000):
    """
    Fetches completed trades for the Journal.
    Ordered by exit_time DESC.
    """
    if not supabase: return []
    try:
        response = supabase.table("trade_history")\
            .select("*")\
            .order("exit_time", desc=True)\
            .limit(limit)\
            .execute()
            
        if response.data:
            return response.data
        return []
    except Exception as e:
        logger.error(f"❌ Error fetching trade history: {e}")
        return []

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

def log_trade_execution(pos, exit_price, exit_reason, leverage=1.0):
    """
    Centralized helper to calculate financial metrics and log trade to DB.
    SYNCHRONOUS to guarantee data persistence before position is cleared.
    """
    try:
        trade_log = pos.copy()
        
        # Calculate P&L
        qty = int(pos.get('qty', 0))
        entry_price = float(pos.get('entry_price', 0))
        pnl = (exit_price - entry_price) * qty
        
        # Calculate Financials
        investment_amount = entry_price * qty
        margin_used = investment_amount / leverage if leverage > 0 else investment_amount
        
        # Enrich Trade Log
        trade_log['pnl'] = pnl
        trade_log['exit_price'] = exit_price
        trade_log['exit_reason'] = exit_reason
        trade_log['exit_time'] = datetime.now().isoformat()
        
        # Add Extra Metadata for Analytics
        trade_log['investment_amount'] = investment_amount
        trade_log['margin_used'] = margin_used
        trade_log['leverage'] = leverage
        
        # Log to Database SYNCHRONOUSLY (blocking to prevent data loss)
        log_trade_to_db(trade_log)
        
        logger.info(f"📝 Trade Logged: {pos.get('symbol')} | P&L: ₹{pnl:,.2f} | Reason: {exit_reason} | Margin: ₹{margin_used:,.0f} | Lev: {leverage}x")
        
    except Exception as e:
        logger.error(f"❌ Failed to log trade: {e}")
