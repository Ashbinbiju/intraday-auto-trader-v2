from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
import threading
import uvicorn
import logging
import os
import asyncio
import main
from main import (
    run_bot_loop, 
    BOT_STATE, 
    place_sell_order,
    place_sell_order_with_retry
)
from config import config_manager
from ws_hub import manager
from state_manager import save_state, state_lock
from datetime import datetime

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API")

# ----------------------------------
# Bot Thread Startup (Modern Lifespan)
# ----------------------------------

from smart_websocket import OrderUpdateWS

async def start_order_update_ws():
    """
    Waits for Broker session and starts Order Update WS (if supported).
    """
    logger.info("Waiting for Broker Session to initialize...")
    max_retries = 60  # Timeout after ~2 minutes
    retries = 0
    
    while retries < max_retries:
        if getattr(main, 'DHAN_API_SESSION', None): # Session exists
            broker = config_manager.get("general", "broker") or "dhan"
            
            if broker == "dhan":
                # Dhan Credentials
                client_id = config_manager.get("credentials", "dhan_client_id")
                access_token = config_manager.get("credentials", "dhan_access_token")
                logger.info("Session Found! Starting Dhan Order Update WebSocket...")
                order_ws = OrderUpdateWS(client_id, access_token, BOT_STATE, manager)
                await order_ws.connect_async()
            elif broker == "angelone":
                from angel_order_ws import AngelOrderWS
                logger.info("Session Found! Starting Angel Order Update WebSocket...")
                order_ws = AngelOrderWS(main.DHAN_API_SESSION, BOT_STATE, manager)
                await order_ws.connect_async()
            break
            
        await asyncio.sleep(2)
        retries += 1
    else:
        logger.error("Timeout waiting for Broker session to initialize.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern FastAPI lifespan handler (replaces deprecated @app.on_event)
    """
    logger.info("🚀 Starting Bot Thread with WS Support...")
    loop = asyncio.get_running_loop()
    bot_thread = threading.Thread(target=run_bot_loop, args=(loop, manager), daemon=True)
    bot_thread.start()
    logger.info("✅ Bot Thread Started Successfully")
    
    # Start Order WS Background Task
    asyncio.create_task(start_order_update_ws())
    
    yield  # Application runs here
    
    # Cleanup on shutdown (if needed)
    logger.info("Shutting down bot...")

app = FastAPI(title="IntradayScreener Bot API v2.0", lifespan=lifespan)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models for Config ---
class RiskConfig(BaseModel):
    stop_loss_pct: float
    target_pct: float
    trail_be_trigger: float

class LimitsConfig(BaseModel):
    max_trades_per_day: int
    max_trades_per_stock: int
    trading_start_time: str
    trading_end_time: str

class GeneralConfig(BaseModel):
    broker: str
    quantity: int
    check_interval: int
    dry_run: bool

class PositionSizingConfig(BaseModel):
    mode: str
    risk_per_trade_pct: float
    max_position_size_pct: float
    min_sl_distance_pct: float
    paper_trading_balance: float
    leverage_equity: float

class CredentialsConfig(BaseModel):
    dhan_client_id: str
    dhan_access_token: str
    smart_api_api_key: str
    angel_api_key: str
    angel_client_id: str
    angel_pin: str
    angel_totp_secret: str

class FullConfig(BaseModel):
    risk: RiskConfig
    limits: LimitsConfig
    general: GeneralConfig
    position_sizing: PositionSizingConfig
    credentials: CredentialsConfig

@app.get("/")
@app.head("/")
def read_root():
    return {"status": "Device Online", "service": "IntradayScreener Bot v2.0"}

@app.get("/data")
def get_bot_data():
    return BOT_STATE

@app.get("/config")
def get_config():
    return config_manager.get_all()

@app.post("/config")
def update_config(config: FullConfig):
    try:
        config_manager.update("risk", config.risk.dict())
        config_manager.update("limits", config.limits.dict())
        config_manager.update("general", config.general.dict())
        config_manager.update("position_sizing", config.position_sizing.dict())
        config_manager.update("credentials", config.credentials.dict())
        return {"status": "success", "message": "Config updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/toggle")
def toggle_trading():
    with state_lock:
        BOT_STATE["is_trading_allowed"] = not BOT_STATE["is_trading_allowed"]
        save_state(BOT_STATE)
        new_state = BOT_STATE["is_trading_allowed"]
    return {"status": "success", "is_trading_allowed": new_state}

@app.post("/trade/close/{symbol}")
async def close_position(symbol: str):
    # 1. Read necessary data under lock
    with state_lock:
        if symbol not in BOT_STATE["positions"]:
            raise HTTPException(status_code=404, detail="Position not found")
        
        pos_data = BOT_STATE["positions"][symbol]
        if pos_data["status"] != "OPEN":
            raise HTTPException(status_code=400, detail="Position already closed")
            
        qty = pos_data['qty']
        current_ltp = pos_data.get('current_ltp', 0.0)
    
    # 2. Perform Network I/O outside lock
    from main import TOKEN_MAP, DHAN_API_SESSION
    token = TOKEN_MAP.get(symbol)
    if not token:
        raise HTTPException(status_code=500, detail="Token not found")
    
    try:
        order_id, verified, exec_price = place_sell_order_with_retry(DHAN_API_SESSION, symbol, token, qty, reason="MANUAL_CLOSE")
        
        # Determine the final exit price (fallback to LTP if verification fails but order placed)
        final_exit_price = exec_price if exec_price and exec_price > 0 else current_ltp
        
        # 3. Update State under lock
        with state_lock:
            if symbol in BOT_STATE["positions"]:
                pos = BOT_STATE["positions"][symbol]
                pos['status'] = "CLOSED"
                pos['exit_reason'] = "MANUAL_CLOSE"
                pos['exit_price'] = final_exit_price
                pos['exit_time'] = datetime.now().isoformat()
                pos_copy = dict(pos) # Copy for logging
                save_state(BOT_STATE)
            else:
                pos_copy = None
                
        # 4. Database I/O outside lock
        if pos_copy:
            from database import log_trade_execution
            from config import config_manager
            
            leverage = config_manager.get("position_sizing", "leverage_equity") or 1.0
            log_trade_execution(pos_copy, final_exit_price, "MANUAL_CLOSE", leverage)
        
        # 5. Broadcast (async network I/O) outside lock
        from ws_hub import manager
        await manager.broadcast(BOT_STATE)
        
        return {"status": "success", "message": f"Closed {symbol}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/portfolio")
def get_portfolio():
    from broker_router import fetch_holdings
    if getattr(main, 'DHAN_API_SESSION', None) is None:
        raise HTTPException(status_code=503, detail="Broker not connected")
    
    holdings = fetch_holdings(main.DHAN_API_SESSION)
    return {"status": "success", "data": holdings}

@app.post("/angel-postback")
async def angel_postback(request: Request):
    """
    Angel One Postback/Webhook for real-time order updates.
    Acts as a highly reliable fallback if the WebSocket disconnects.
    """
    try:
        data = await request.json()
        status = data.get("status", "").lower()
        ordertag = data.get("ordertag", "")
        symbol = data.get("tradingsymbol", "").replace("-EQ", "")
        
        logger.info(f"Postback Event: {symbol} | Status: {status} | Tag: {ordertag}")
        
        if status in ["complete", "rejected", "cancelled"]:
            from main import DHAN_API_SESSION
            from angel_order_ws import AngelOrderWS
            # Re-use the existing Execution handler logic from the WebSocket class
            handler = AngelOrderWS(DHAN_API_SESSION, BOT_STATE, manager)
            handler._handle_execution(symbol, ordertag, status, data)
            
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Postback error: {e}")
        return {"status": "error"}

@app.post("/restart")
def restart_server():
    """
    Kills the server process. 
    On Render/Container environments, this triggers an automatic restart.
    """
    def kill():
        import time
        time.sleep(1)
        os._exit(1)
        
    threading.Thread(target=kill).start()
    return {"status": "success", "message": "Server restarting in 1s..."}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Send Heartbeat Ping every 15s to keep connection alive
            # Fixing 'connection close' issue on cloud providers (AWS/Render)
            await asyncio.sleep(15)
            try:
                await websocket.send_json({"type": "ping", "timestamp": str(datetime.now())})
            except Exception as e:
                # If send fails, client is gone. Break loop to trigger disconnect.
                logger.debug(f"WS Ping Failed: {e}")
                break
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS Endpoint Error: {e}")
        manager.disconnect(websocket)

# --- Journal / History ---

@app.get("/api/trades/history")
async def get_trade_history_api():
    """
    Fetches historical completed trades from DB for the Journal.
    """
    try:
        import database
        # Fetch last 500 trades
        trades = database.fetch_trade_history(limit=500)
        return {"trades": trades}
    except Exception as e:
        logger.error(f"Error fetching trade history: {e}")
        # Return empty list on error to prevent frontend crash
        return {"trades": []}

# ----------------------------------
# Keep-Alive (Render Free Tier)
# ----------------------------------

def start_keep_alive():
    """
    Pings the application's own URL every 10 minutes to prevent Render from sleeping.
    Relies on RENDER_EXTERNAL_URL environment variable.
    """
    import time
    import requests
    import os
    
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        logger.info("Keep-Alive: No RENDER_EXTERNAL_URL found. Skipping.")
        return

    logger.info(f"Keep-Alive: Starting self-ping for {url}")
    
    def loop():
        while True:
            time.sleep(600) # 10 Minutes
            try:
                # Ping root or a health endpoint
                r = requests.get(f"{url}/", timeout=30)
                logger.info(f"Keep-Alive Ping: {r.status_code}")
            except Exception as e:
                logger.error(f"Keep-Alive Failed: {e}")
                
    t = threading.Thread(target=loop, daemon=True)
    t.start()

if __name__ == "__main__":
    # Start Keep-Alive before server
    start_keep_alive()
    
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
