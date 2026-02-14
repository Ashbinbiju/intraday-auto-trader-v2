import logging
import threading
import time
import json
from dhanhq import DhanContext, OrderUpdate
from config import config_manager
from state_manager import state_lock

logger = logging.getLogger("DhanOrderSocket")

def _patch_dhan_websocket():
    """
    Monkey-patch dhanhq.OrderSocket to handle concatenated JSON messages.
    Dhan sends multiple JSON objects in one WebSocket message without separators.
    """
    try:
        from dhanhq.orderupdate import OrderSocket
        
        # Save original connect method
        original_connect = OrderSocket.connect_order_update
        
        async def patched_connect(self):
            """Patched version that handles multiple JSON objects"""
            import websockets
            async with websockets.connect(self.order_feed_wss) as websocket:
                auth_message = {
                    "LoginReq": {
                        "MsgCode": 42,
                        "ClientId": str(self.client_id),
                        "Token": str(self.access_token)
                    },
                    "UserType": "SELF"
                }
                
                await websocket.send(json.dumps(auth_message))
                logger.info("✅ Dhan WebSocket authenticated")
                
                async for message in websocket:
                    # Handle multiple concatenated JSON objects
                    try:
                        message_str = message.strip()
                        if not message_str:
                            continue
                        
                        decoder = json.JSONDecoder()
                        idx = 0
                        while idx < len(message_str):
                            try:
                                data, end_idx = decoder.raw_decode(message_str, idx)
                                await self.handle_order_update(data)
                                idx = end_idx
                                # Skip whitespace
                                while idx < len(message_str) and message_str[idx].isspace():
                                    idx += 1
                            except json.JSONDecodeError:
                                if idx < len(message_str):
                                    logger.debug(f"Unparsed data remaining at idx {idx}: {message_str[idx:idx+50]!r}...")
                                break
                    except (TypeError, AttributeError):
                        logger.exception("JSON parse error")
        
        # Apply monkey-patch
        OrderSocket.connect_order_update = patched_connect
        logger.info("✅ Dhan WebSocket patch applied")
        return True
    except (ImportError, AttributeError) as e:
        logger.warning(f"⚠️  Could not patch Dhan SDK: {e}")
        return False

def start_dhan_websocket(bot_state):
    """
    Dhan Order Update WebSocket - DISABLED due to SDK bug.
    
    Issue: dhanhq==2.2.0rc1 has a JSON parsing bug where it cannot handle
    concatenated JSON objects sent by Dhan's WebSocket server.
    Error: "Extra data: line 2 column 1 (char 2)"
    
    This is a bug in the installed package itself, not our implementation.
    Order status is still tracked via REST API polling in main loop.
    
    If Dhan fixes this in a future SDK release, re-enable by uncommenting below.
    """
    logger.info("ℹ️  Dhan Order WebSocket disabled (SDK has JSON parsing bug)")
    logger.info("📡 Order status tracked via REST API polling instead")
    return None
    
    # Original implementation (correct pattern, but SDK has bug):
    # order_client = OrderUpdate(dhan_context)
    # order_client.on_update = on_order_update
    # order_client.connect_to_dhan_websocket_sync()
