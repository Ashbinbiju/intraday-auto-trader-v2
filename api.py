from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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

app = FastAPI(title="IntradayScreener Bot API v2.0")

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

class FullConfig(BaseModel):
    risk: RiskConfig
    limits: LimitsConfig
    general: GeneralConfig
    position_sizing: PositionSizingConfig

# ----------------------------------

from smart_websocket import OrderUpdateWS

async def start_order_update_ws():
    """
    Waits for SmartAPI session and starts Order Update WS.
    """
    logger.info("Waiting for SmartAPI Session to initialize...")
    while True:
        if main.SMART_API_SESSION and hasattr(main.SMART_API_SESSION, 'jwt_token'):
            token = main.SMART_API_SESSION.jwt_token
            logger.info("Session Found! Starting Order Update WebSocket...")
            order_ws = OrderUpdateWS(token, BOT_STATE, manager)
            # Run in loop
            await order_ws.connect()
            break
        await asyncio.sleep(2)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Bot Thread with WS Support...")
    loop = asyncio.get_running_loop()
    bot_thread = threading.Thread(target=run_bot_loop, args=(loop, manager), daemon=True)
    bot_thread.start()
    
    # Start Order WS Background Task
    asyncio.create_task(start_order_update_ws())

@app.get("/")
def read_root():
    return {"status": "Device Online", "service": "IntradayScreener Bot v2.0"}

@app.get("/data")
def get_bot_data():
    return BOT_STATE

# --- Settings Endpoints ---
@app.get("/settings")
def get_settings():
    return config_manager.config

@app.post("/settings")
async def update_settings(config: FullConfig):
    try:
        # Update Config
        config_manager.set(["risk", "stop_loss_pct"], config.risk.stop_loss_pct)
        config_manager.set(["risk", "target_pct"], config.risk.target_pct)
        config_manager.set(["risk", "trail_be_trigger"], config.risk.trail_be_trigger)
        
        config_manager.set(["limits", "max_trades_per_day"], config.limits.max_trades_per_day)
        config_manager.set(["limits", "max_trades_per_stock"], config.limits.max_trades_per_stock)
        config_manager.set(["limits", "trading_start_time"], config.limits.trading_start_time)
        config_manager.set(["limits", "trading_end_time"], config.limits.trading_end_time)
        
        config_manager.set(["general", "quantity"], config.general.quantity)
        config_manager.set(["general", "check_interval"], config.general.check_interval)
        config_manager.set(["general", "dry_run"], config.general.dry_run)

        # Update Position Sizing
        config_manager.set(["position_sizing", "mode"], config.position_sizing.mode)
        config_manager.set(["position_sizing", "risk_per_trade_pct"], config.position_sizing.risk_per_trade_pct)
        config_manager.set(["position_sizing", "max_position_size_pct"], config.position_sizing.max_position_size_pct)
        config_manager.set(["position_sizing", "min_sl_distance_pct"], config.position_sizing.min_sl_distance_pct)
        config_manager.set(["position_sizing", "paper_trading_balance"], config.position_sizing.paper_trading_balance)

        # FORCE STATE UPDATE
        with state_lock:
            if "limits" not in BOT_STATE: BOT_STATE["limits"] = {}
            BOT_STATE["limits"]["max_trades_day"] = config.limits.max_trades_per_day
            BOT_STATE["limits"]["max_trades_stock"] = config.limits.max_trades_per_stock
            BOT_STATE["limits"]["trading_start_time"] = config.limits.trading_start_time
            BOT_STATE["limits"]["trading_end_time"] = config.limits.trading_end_time
            
            # Broadcast immediately
            await manager.broadcast(BOT_STATE)
            save_state(BOT_STATE)
        
        return {"message": "Configuration updated successfully"}
    except Exception as e:
        logger.error(f"Error updating config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Trade Management ---
@app.post("/bot/kill-switch")
async def kill_switch():
    """
    Stops all new entries immediately.
    """
    with state_lock:
        BOT_STATE["is_trading_allowed"] = False
        logger.warning("KILL SWITCH ACTIVATED via API")
        await manager.broadcast(BOT_STATE)
        save_state(BOT_STATE)
    return {"message": "Kill Switch Activated. No new trades will be taken."}

@app.post("/bot/resume")
async def resume_trading():
    """
    Resumes trading.
    """
    with state_lock:
        BOT_STATE["is_trading_allowed"] = True
        logger.info("Trading Resumed via API")
        await manager.broadcast(BOT_STATE)
        save_state(BOT_STATE)
    return {"message": "Trading Resumed."}

@app.post("/trade/close/{symbol}")
async def close_trade(symbol: str):
    """
    Manually closes an active position.
    """
    # Check if position exists
    if symbol not in BOT_STATE["positions"] or BOT_STATE["positions"][symbol]["status"] != "OPEN":
        raise HTTPException(status_code=404, detail="Active position not found")
    
    if not main.SMART_API_SESSION or not main.TOKEN_MAP:
        raise HTTPException(status_code=503, detail="Bot not fully initialized (No Session/TokenMap)")

    token = main.TOKEN_MAP.get(symbol)
    qty = BOT_STATE["positions"][symbol]["qty"]
    
    # Execute Sell
    order_id = place_sell_order(main.SMART_API_SESSION, symbol, token, qty, reason="MANUAL_API_EXIT")
    
    if order_id or config_manager.get("general", "dry_run"):
        # Fetch current LTP as exit price
        try:
            from smart_api_helper import fetch_ltp
            exit_price = fetch_ltp(main.SMART_API_SESSION, token, symbol)
            if exit_price is None or exit_price == 0:
                # Fallback: Use entry price if LTP fetch fails
                exit_price = BOT_STATE["positions"][symbol].get("entry_price", 0)
        except Exception:
            # Fallback on error
            exit_price = BOT_STATE["positions"][symbol].get("entry_price", 0)
        
        # Update State
        with state_lock:
            BOT_STATE["positions"][symbol]["status"] = "CLOSED"
            BOT_STATE["positions"][symbol]["exit_price"] = exit_price
            BOT_STATE["positions"][symbol]["exit_reason"] = "MANUAL"
            await manager.broadcast(BOT_STATE)
            save_state(BOT_STATE)
        return {"message": f"Sell Order Placed for {symbol}", "order_id": order_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to place sell order")

@app.post("/tool/margin")
def get_margin(positions: list):
    """
    Calculates required margin for a list of positions.
    """
    if not main.SMART_API_SESSION or not hasattr(main.SMART_API_SESSION, 'jwt_token'):
        raise HTTPException(status_code=503, detail="Bot not fully initialized")
    
    from smart_api_helper import calculate_margin
    margin_data = calculate_margin(main.SMART_API_SESSION, positions)
    
    if margin_data:
        return margin_data
    else:
        raise HTTPException(status_code=500, detail="Margin Calculation Failed")

@app.get("/portfolio/holdings")
def get_holdings():
    """
    Fetches Equity Holdings.
    """
    if not main.SMART_API_SESSION or not hasattr(main.SMART_API_SESSION, 'jwt_token'):
        raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import fetch_holdings
    return fetch_holdings(main.SMART_API_SESSION) or []

@app.get("/portfolio/all-holdings")
def get_all_holdings():
    """
    Fetches All Holdings with Summary.
    """
    if not main.SMART_API_SESSION or not hasattr(main.SMART_API_SESSION, 'jwt_token'):
        raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import fetch_all_holdings
    return fetch_all_holdings(main.SMART_API_SESSION) or {}

@app.get("/portfolio/positions")
def get_positions():
    """
    Fetches Broker's Net Positions (Live).
    """
    if not main.SMART_API_SESSION: 
        raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import fetch_net_positions
    return fetch_net_positions(main.SMART_API_SESSION) or []

@app.post("/portfolio/convert")
def convert_pos(payload: dict):
    """
    Converts Position Product Type.
    """
    if not main.SMART_API_SESSION or not hasattr(main.SMART_API_SESSION, 'jwt_token'):
        raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import convert_position
    return convert_position(main.SMART_API_SESSION, payload)

@app.post("/tool/brokerage")
def get_brokerage(payload: dict):
    """
    Calculates Brokerage.
    Payload: { "orders": [...] }
    """
    if not main.SMART_API_SESSION or not hasattr(main.SMART_API_SESSION, 'jwt_token'):
        raise HTTPException(status_code=503, detail="Bot not fully initialized")
    
    orders = payload.get("orders", [])
    if not orders:
        raise HTTPException(status_code=400, detail="Missing orders list")

    from smart_api_helper import calculate_brokerage
    data = calculate_brokerage(main.SMART_API_SESSION, orders)
    
    if data:
        return data
    else:
        raise HTTPException(status_code=500, detail="Brokerage Calculation Failed")

# --- Order Management Endpoints ---
@app.post("/order/place")
def place_order(payload: dict):
    if not main.SMART_API_SESSION: raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import place_order_api
    res = place_order_api(main.SMART_API_SESSION, payload)
    if res: return {"orderid": res}
    raise HTTPException(status_code=500, detail="Order Placement Failed")

@app.post("/order/modify")
def modify_order(payload: dict):
    if not main.SMART_API_SESSION: raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import modify_order_api
    res = modify_order_api(main.SMART_API_SESSION, payload)
    if res: return res
    raise HTTPException(status_code=500, detail="Modify Order Failed")

@app.post("/order/cancel")
def cancel_order(payload: dict):
    if not main.SMART_API_SESSION: raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import cancel_order_api
    order_id = payload.get("orderid")
    variety = payload.get("variety", "NORMAL")
    res = cancel_order_api(main.SMART_API_SESSION, order_id, variety)
    if res: return res
    raise HTTPException(status_code=500, detail="Cancel Order Failed")

@app.get("/order/book")
def get_order_book():
    if not main.SMART_API_SESSION: raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import fetch_all_orders
    return fetch_all_orders(main.SMART_API_SESSION)

@app.get("/order/trades")
def get_trade_book():
    if not main.SMART_API_SESSION: raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import fetch_trade_book
    return fetch_trade_book(main.SMART_API_SESSION)

@app.post("/order/ltp")
def get_ltp(payload: dict):
    if not main.SMART_API_SESSION: raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import get_ltp_data
    return get_ltp_data(main.SMART_API_SESSION, payload.get("exchange"), payload.get("tradingsymbol"), payload.get("symboltoken"))

@app.get("/order/details/{order_id}")
def get_order_details(order_id: str):
    if not main.SMART_API_SESSION: raise HTTPException(status_code=503, detail="Bot not fully initialized")
    from smart_api_helper import get_individual_order
    return get_individual_order(main.SMART_API_SESSION, order_id)

@app.post("/webhook/angel-one")
async def angel_one_postback(request: dict):
    """
    Receives Order Updates via Webhook (Postback).
    Note: Requires HTTPS/Public IP to function with Angel One.
    """
    try:
        logger.info(f"WEBHOOK RECEIVED: {request}")
        
        # Extract relevant data
        symbol = request.get("tradingsymbol", "").replace("-EQ", "")
        status = request.get("orderstatus", "").lower()
        trans_type = request.get("transactiontype")
        price = float(request.get("averageprice", 0) or 0)
        
        with state_lock:
            if status == "complete":
                 if trans_type == "SELL":
                     if symbol in BOT_STATE["positions"]:
                         BOT_STATE["positions"][symbol]["status"] = "CLOSED"
                         BOT_STATE["positions"][symbol]["exit_price"] = price
                         BOT_STATE["positions"][symbol]["exit_reason"] = "WEBHOOK"
                         logger.info(f"Position Closed via Webhook for {symbol}")
                         
                 elif trans_type == "BUY":
                      if symbol in BOT_STATE["positions"]:
                          BOT_STATE["positions"][symbol]["status"] = "OPEN"
                          BOT_STATE["positions"][symbol]["entry_price"] = price
            
            # Broadcast Update
            await manager.broadcast(BOT_STATE)
            save_state(BOT_STATE)
        
        return "OK"
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return "ERROR"

# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # PUSH IMMEDIATE UPDATE (Fixes "Loading..." stuck state)
        await websocket.send_json(BOT_STATE) 
        
        while True:
            # We can listen for messages from client if needed (e.g. heartbeat)
            # For now, just keep connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
# --------------------------

# --- Keep-Alive (Self-Pinger) ---
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
