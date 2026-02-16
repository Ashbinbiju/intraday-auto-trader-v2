import os
import logging
import urllib.request
import urllib.parse
import json
import threading

# Configure Logging
logger = logging.getLogger(__name__)

# Load Credentials (with defaults from user)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7902319450:AAFPNcUyk9F6Sesy-h6SQnKHC_Yr6Uqk9ps")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1002411670969")

def send_telegram_message(message):
    """
    Sends a message to the configured Telegram chat.
    Uses threading to avoid blocking the main bot loop.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials missing. Skipping message.")
        return

    def _send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            }
            data_encoded = urllib.parse.urlencode(data).encode('utf-8')
            
            req = urllib.request.Request(url, data=data_encoded, method='POST')
            with urllib.request.urlopen(req, timeout=5) as response:
                result = json.loads(response.read().decode())
                if not result.get("ok"):
                    logger.error(f"Telegram API Error: {result}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    # Run in a separate thread to prevent blocking
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()

# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    send_telegram_message("🤖 **Bot Initialization Test**\nTelegram notifications are working!")
