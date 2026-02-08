import logging
import asyncio
import websockets
from config import config_manager

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DebugAuthQuery")

DHAN_CLIENT_ID = config_manager.get("credentials", "dhan_client_id")
DHAN_ACCESS_TOKEN = config_manager.get("credentials", "dhan_access_token")

# Try connecting with Query Params (as per Market Feed docs)
# wss://api-order-update.dhan.co?version=2&token=...&clientId=...&authType=2

url = f"wss://api-order-update.dhan.co?version=2&token={DHAN_ACCESS_TOKEN}&clientId={DHAN_CLIENT_ID}&authType=2"

async def test_query_auth():
    logger.info(f"\n--- Testing: Connect with Query Params ---")
    logger.info(f"URL: {url.replace(DHAN_ACCESS_TOKEN, '****')}")
    
    try:
        async with websockets.connect(url, ping_timeout=None) as ws:
            logger.info("✅ Connected (WebSocket Handshake Success)")
            
            # Wait for any message (Greeting or Error)
            try:
                for i in range(3):
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    if isinstance(msg, bytes):
                        logger.info(f"Msg {i+1} - Received Binary: {msg.hex()} (Len: {len(msg)})")
                        # 0x32 (50) = Disconnect
                        if msg[0] == 50:
                            # 0x32 0a 00 28 03 -> 50 10 0 40 3
                            # Why 28 03 = 808? (0x0328 = 808) 
                            # If Little Endian: 28 03 -> 0x0328 = 808
                            logger.error("❌ Received Disconnect Packet (likely 808 Auth Failed)")
                    else:
                        logger.info(f"Msg {i+1} - Received Text: {msg}")
            except asyncio.TimeoutError:
                logger.info("Timeout: No immediate disconnect. Maybe Auth Success?")
            except Exception as e:
                logger.error(f"Error reading: {e}")
                
    except Exception as e:
        logger.error(f"Connection Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_query_auth())
