import time
import threading
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import test_angel_data

def test_angel_ws():
    session = test_angel_data.get_session()
    if not session:
        print("Failed to get session")
        return
        
    auth_token = session.access_token
    api_key = session.api_key
    client_code = session.userId
    feed_token = session.feed_token
    
    print(f"Connecting with client_code={client_code}")
    
    ws = SmartWebSocketV2(auth_token, api_key, client_code, feed_token)
    
    def on_data(wsapp, message):
        print("on_data:", message)
        
    def on_open(wsapp):
        print("on_open")
        # Subscribe to SBIN (token 3045)
        # Mode: 1 (LTP), exchangeType: 1 (NSE_CM)
        token_list = [{"exchangeType": 1, "tokens": ["3045"]}]
        ws.subscribe("abcde12345", 1, token_list)
        
    def on_error(wsapp, error):
        print("on_error:", error)
        
    def on_close(wsapp, close_status_code, close_msg):
        print("on_close:", close_status_code, close_msg)
        
    ws.on_open = on_open
    ws.on_data = on_data
    ws.on_error = on_error
    ws.on_close = on_close
    
    # Run in background
    t = threading.Thread(target=ws.connect)
    t.daemon = True
    t.start()
    
    time.sleep(10)
    ws.close_connection()
    print("Done")

if __name__ == "__main__":
    test_angel_ws()
