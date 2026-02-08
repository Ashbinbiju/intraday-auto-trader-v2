import logging
import json
import websockets
import asyncio
from config import config_manager

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DebugAuth")

DHAN_CLIENT_ID = config_manager.get("credentials", "dhan_client_id")
DHAN_ACCESS_TOKEN = config_manager.get("credentials", "dhan_access_token")

url = "wss://api-order-update.dhan.co"

async def test_no_auth():
    logger.info("\n--- Testing: Connect & Send Nothing ---")
    try:
        async with websockets.connect(url, ping_timeout=None) as ws:
            logger.info("✅ Connected")
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                if isinstance(msg, bytes):
                    logger.info(f"Received Binary: {msg.hex()}")
                else:
                    logger.info(f"Received Text: {msg}")
            except asyncio.TimeoutError:
                logger.info("Timeout: No data received without auth.")
            except Exception as e:
                logger.error(f"Error: {e}")
    except Exception as e:
        logger.error(f"Connection Failed: {e}")

async def test_bad_auth():
    logger.info("\n--- Testing: Connect & Send BAD Auth ---")
    try:
        async with websockets.connect(url, ping_timeout=None) as ws:
            logger.info("✅ Connected")
            bad_auth = {
                "LoginReq": {
                    "MsgCode": 42,
                    "ClientId": "BAD_ID",
                    "Token": "BAD_TOKEN"
                },
                "UserType": "SELF"
            }
            logger.info(f"Sending: {json.dumps(bad_auth)}")
            await ws.send(json.dumps(bad_auth))
            
            try:
                # Read 2 messages just in case
                for i in range(2):
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    if isinstance(msg, bytes):
                        logger.info(f"Msg {i+1} - Received Binary: {msg.hex()}")
                    else:
                        logger.info(f"Msg {i+1} - Received Text: {msg}")
            except asyncio.TimeoutError:
                logger.info("Timeout waiting for response.")
            except Exception as e:
                logger.error(f"Error: {e}")
    except Exception as e:
        logger.error(f"Connection Failed: {e}")

async def test_good_auth():
    logger.info("\n--- Testing: Connect & Send GOOD Auth ---")
    try:
        async with websockets.connect(url, ping_timeout=None) as ws:
            logger.info("✅ Connected")
            good_auth = {
                "LoginReq": {
                    "MsgCode": 42,
                    "ClientId": str(DHAN_CLIENT_ID),
                    "Token": str(DHAN_ACCESS_TOKEN)
                },
                "UserType": "SELF"
            }
            logger.info(f"Sending GOOD Auth for Client: {DHAN_CLIENT_ID}")
            await ws.send(json.dumps(good_auth))
            
            try:
                # Read more messages to see heartbeat pattern
                for i in range(5):
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    if isinstance(msg, bytes):
                        logger.info(f"Msg {i+1} - Received Binary: {msg.hex()}")
                        # Try echoing if it's 32...
                        if msg[0] == 50:
                            logger.info("Echoing...")
                            await ws.send(msg)
                    else:
                        logger.info(f"Msg {i+1} - Received Text: {msg}")
            except asyncio.TimeoutError:
                logger.info("Timeout waiting for response.")
            except Exception as e:
                logger.error(f"Error reading: {e}")
    except Exception as e:
        logger.error(f"Connection Failed: {e}")

async def main():
    await test_no_auth()
    await test_bad_auth()
    await test_good_auth()

if __name__ == "__main__":
    asyncio.run(main())
