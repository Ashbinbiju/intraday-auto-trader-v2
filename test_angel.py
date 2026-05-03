from SmartApi import SmartConnect
import pyotp
from config import config_manager
import logging

logging.basicConfig(level=logging.INFO)

api_key = config_manager.get("credentials", "angel_api_key")
client_id = config_manager.get("credentials", "angel_client_id")
pin = config_manager.get("credentials", "angel_pin")
totp_secret = config_manager.get("credentials", "angel_totp_secret")

print(f"API Key: {api_key}")
print(f"TOTP: {totp_secret}")

obj = SmartConnect(api_key=api_key)

try:
    totp = pyotp.TOTP(totp_secret).now()
    print(f"Generated TOTP: {totp}")
    data = obj.generateSession(client_id, pin, totp)
    if data['status']:
        print("Login Success!")
        print("Token:", data['data']['jwtToken'])
    else:
        print("Login Failed:", data)
except Exception as e:
    print("Error:", e)
