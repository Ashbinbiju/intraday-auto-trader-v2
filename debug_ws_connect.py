import asyncio
import logging
from dhanhq import dhanhq
from dhanhq.orderupdate import OrderSocket
import json
import ssl
import websockets
from config import config_manager

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DebugWS")

DHAN_CLIENT_ID = config_manager.get("credentials", "dhan_client_id")
DHAN_ACCESS_TOKEN = config_manager.get("credentials", "dhan_access_token")

logger.info(f"Testing Client ID: {DHAN_CLIENT_ID}")
masked_token = DHAN_ACCESS_TOKEN[:4] + "****" + DHAN_ACCESS_TOKEN[-4:]
logger.info(f"Testing Token: {masked_token}")

async def test_raw_socket():
    url = "wss://api-order-update.dhan.co"
    logger.info(f"\n--- Testing Raw WebSocket: {url} ---")
    
    try:
        async with websockets.connect(url) as websocket:
            logger.info("✅ Connected")
            
            auth_packet = {
                "LoginReq": {
                    "MsgCode": 42,
                    "ClientId": str(DHAN_CLIENT_ID),
                    "Token": str(DHAN_ACCESS_TOKEN)
                },
                "UserType": "SELF"
            }
            logger.info(f"Sending: {json.dumps(auth_packet)}")
            await websocket.send(json.dumps(auth_packet))
            
            # Read first few messages
            for _ in range(3):
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=5)
                    if isinstance(msg, bytes):
                        logger.warning(f"Received Binary: {msg.hex()} | {msg}")
                    else:
                        logger.info(f"Received Text: {msg}")
                except asyncio.TimeoutError:
                    logger.info("Timeout waiting for message")
                    break
                except Exception as e:
                    logger.error(f"Error reading: {e}")
                    break
                    
    except Exception as e:
        logger.error(f"Raw Socket Failed: {e}")

async def main():
    await test_raw_socket()
    # Note: We can't easily test dhanhq.OrderSocket because it's designed to run forever in a loop
    # but the raw test mimics it exactly.

if __name__ == "__main__":
    asyncio.run(main())
