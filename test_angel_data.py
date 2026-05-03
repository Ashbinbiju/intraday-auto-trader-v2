import logging
from broker_router import get_session, load_instrument_map, fetch_ltp, fetch_candle_data

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger("AngelTest")

def run_test():
    logger.info("Initializing Session...")
    session = get_session()
    if not session:
        logger.error("Failed to get session.")
        return

    logger.info("Loading Instrument Map...")
    token_map = load_instrument_map()
    if not token_map:
        logger.error("Failed to load instrument map.")
        return

    test_symbol = "RELIANCE"
    token = token_map.get(test_symbol)
    logger.info(f"Token for {test_symbol}: {token}")

    logger.info(f"Fetching LTP for {test_symbol}...")
    ltp = fetch_ltp(session, token, test_symbol)
    logger.info(f"LTP: {ltp}")

    logger.info(f"Fetching 5-minute Candles for {test_symbol}...")
    from datetime import datetime, timedelta
    to_date = datetime.now()
    from_date = to_date - timedelta(days=1)
    
    params = {
        "exchange": "NSE",
        "symboltoken": token,
        "interval": "FIVE_MINUTE",
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M")
    }
    print("Calling getCandleData with params:", params)
    resp = session.getCandleData(params)
    print("Raw Response:", resp)

if __name__ == "__main__":
    run_test()
