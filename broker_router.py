import logging
from config import config_manager
import dhan_api_helper
import angel_api_helper

logger = logging.getLogger("BrokerRouter")

def get_active_broker():
    """Returns the active broker string ('dhan' or 'angelone')"""
    return config_manager.get("general", "broker") or "dhan"

def get_broker_module():
    """Returns the API helper module for the active broker"""
    broker = get_active_broker()
    if broker == "angelone":
        return angel_api_helper
    else:
        # Default to DhanHQ
        return dhan_api_helper

# --- Router Functions ---

def get_session():
    module = get_broker_module()
    # Dhan uses get_dhan_session, Angel uses get_session. 
    # For compatibility, we standardise here:
    if hasattr(module, 'get_session'):
        return module.get_session()
    elif hasattr(module, 'get_dhan_session'):
        return module.get_dhan_session()
    return None

def check_connection(session):
    module = get_broker_module()
    if hasattr(module, 'check_connection'):
        return module.check_connection(session)
    logger.warning("check_connection not available for active broker")
    return False, "METHOD_MISSING"

def load_instrument_map():
    module = get_broker_module()
    if hasattr(module, 'load_instrument_map'):
        return module.load_instrument_map()
    elif hasattr(module, 'load_dhan_instrument_map'):
        return module.load_dhan_instrument_map()
    return {}

def fetch_ltp(session, token, symbol):
    broker = get_active_broker()
    if broker == "angelone":
        try:
            from angel_stream_ws import LIVE_LTP_DICT
            if str(token) in LIVE_LTP_DICT:
                return LIVE_LTP_DICT[str(token)]
        except ImportError:
            pass

    module = get_broker_module()
    if hasattr(module, 'fetch_ltp'):
        return module.fetch_ltp(session, token, symbol)
    logger.warning("fetch_ltp not available for active broker")
    return None

def fetch_candle_data(session, token, symbol, interval="FIVE_MINUTE", days=10):
    module = get_broker_module()
    return module.fetch_candle_data(session, token, symbol, interval, days)

def place_order_api(session, params):
    module = get_broker_module()
    return module.place_order_api(session, params)

def fetch_net_positions(session):
    module = get_broker_module()
    return module.fetch_net_positions(session)

def get_order_status(session, order_id):
    module = get_broker_module()
    return module.get_order_status(session, order_id)

def verify_order_status(session, symbol, correlation_id):
    module = get_broker_module()
    if hasattr(module, 'verify_order_status'):
        return module.verify_order_status(session, symbol, correlation_id)
    return False

def fetch_market_feed_bulk(session, token_list):
    broker = get_active_broker()
    if broker == "angelone":
        try:
            from angel_stream_ws import LIVE_LTP_DICT
            feed = {}
            for token in token_list:
                if str(token) in LIVE_LTP_DICT:
                    feed[str(token)] = LIVE_LTP_DICT[str(token)]
            return feed
        except ImportError:
            return {}

    module = get_broker_module()
    if hasattr(module, 'fetch_market_feed_bulk'):
        return module.fetch_market_feed_bulk(session, token_list)
    return {}

def fetch_holdings(session):
    module = get_broker_module()
    if hasattr(module, 'fetch_holdings'):
        return module.fetch_holdings(session)
    return None
