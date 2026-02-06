from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
    place_sell_order
)
from config import config_manager
from ws_hub import manager
from state_manager import save_state, state_lock

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API")

# ----------------------------------
# Bot Thread Startup (Modern Lifespan)
# ----------------------------------

from smart_websocket import OrderUpdateWS

async def start_order_update_ws():
    """
    Waits for SmartAPI session and starts Order Update WS.
    """
    logger.info("Waiting for Dhan API Session to initialize...")
    while True:
        if main.SMART_API_SESSION: # Check connectivity (Dhan object exists)
            # Get IDs from config
            client_id = config_manager.get("credentials", "dhan_client_id")
            access_token = config_manager.get("credentials", "dhan_access_token")
            
            logger.info("Session Found! Starting Order Update WebSocket...")
            order_ws = OrderUpdateWS(client_id, access_token, BOT_STATE, manager)
            # Run in loop
            await order_ws.connect()
            break
        await asyncio.sleep(2)

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
    quantity: int
    check_interval: int
    dry_run: bool

class PositionSizingConfig(BaseModel):
    mode: str
    risk_per_trade_pct: float
    max_position_size_pct: float
    min_sl_distance_pct: float
    paper_trading_balance: float

class CredentialsConfig(BaseModel):
    dhan_client_id: str
    dhan_access_token: str

class FullConfig(BaseModel):
    risk: RiskConfig
    limits: LimitsConfig
    general: GeneralConfig
    position_sizing: PositionSizingConfig
    credentials: CredentialsConfig

@app.get("/")
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
    return {"status": "success", "is_trading_allowed": BOT_STATE["is_trading_allowed"]}

@app.post("/close/{symbol}")
def close_position(symbol: str):
    with state_lock:
        if symbol not in BOT_STATE["positions"]:
            raise HTTPException(status_code=404, detail="Position not found")
        
        pos = BOT_STATE["positions"][symbol]
        if pos["status"] != "OPEN":
            raise HTTPException(status_code=400, detail="Position already closed")
        
        # Get token from instrument map
        from main import TOKEN_MAP, SMART_API_SESSION
        token = TOKEN_MAP.get(symbol)
        if not token:
            raise HTTPException(status_code=500, detail="Token not found")
        
        # Place sell order
        try:
            place_sell_order(SMART_API_SESSION, symbol, token, pos['qty'], reason="MANUAL_CLOSE")
            pos['status'] = "CLOSED"
            pos['exit_reason'] = "MANUAL_CLOSE"
            save_state(BOT_STATE)
            return {"status": "success", "message": f"Closed {symbol}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

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
            # Keep connection alive (client will receive broadcasts)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

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
                r = requests.get(f"{url}/")
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
