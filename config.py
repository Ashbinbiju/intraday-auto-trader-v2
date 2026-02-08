import json
import os
import logging
from database import get_remote_config, save_remote_config

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "risk": {
        "stop_loss_pct": 0.01,       # 1.0%
        "target_pct": 0.02,          # 2.0%
        "trail_be_trigger": 0.012    # 1.2%
    },
    "limits": {
        "max_trades_per_day": 3,
        "max_trades_per_stock": 2,
        "trading_start_time": "09:20",
        "trading_end_time": "11:00"
    },
    "general": {
        "quantity": 1,
        "check_interval": 300,       # 5 minutes
        "dry_run": True,
        "strategy_mode": "SECTOR_MOMENTUM" # Options: SECTOR_MOMENTUM, MARKET_MOVER
    },
    "position_sizing": {
        "mode": "dynamic",
        "risk_per_trade_pct": 1.0,
        "max_position_size_pct": 20.0,
        "min_sl_distance_pct": 0.6,
        "paper_trading_balance": 100000
    },
    "credentials": {
        "dhan_client_id": "",
        "dhan_access_token": "",
        "smart_api_api_key": ""
    }
}

class ConfigManager:
    def __init__(self):
        self.config = DEFAULT_CONFIG.copy()
        self.load_config()

    def load_config(self):
        # 1. Try Supabase First
        remote_config = get_remote_config()
        if remote_config:
            self.config = self.update_nested(self.config, remote_config)
            logging.info("✅ Config Loaded from Supabase")
            # Sync local file
            self.save_local() 
            return

        # 2. Fallback to Local File
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    saved_config = json.load(f)
                    self.config = self.update_nested(self.config, saved_config)
                    logging.info("✅ Config Loaded from Local File")
            except Exception as e:
                logging.error(f"Error loading local config: {e}")
        else:
            self.save_config()

    def update_nested(self, d, u):
        """Recursively update dictionary d with values from u."""
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = self.update_nested(d.get(k, {}), v)
            else:
                d[k] = v
        return d

    def save_config(self):
        """Saves config to both Local File and Supabase."""
        self.save_local()
        save_remote_config(self.config)

    def save_local(self):
        """Saves config to local disk only."""
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving local config: {e}")

    def get(self, *keys):
        """Get a value by traversing keys."""
        val = self.config
        for k in keys:
            val = val.get(k)
            if val is None:
                return None
        return val

    def set(self, keys, value):
        """Set a value by traversing keys. keys is a list/tuple."""
        d = self.config
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
        d[keys[-1]] = value
        self.save_config()

    def get_all(self):
        """Returns the full configuration dictionary."""
        return self.config

    def update(self, section, value):
        """Updates a configuration section and saves."""
        if section in self.config and isinstance(self.config[section], dict) and isinstance(value, dict):
            self.config[section].update(value)
        else:
            self.config[section] = value
        self.save_config()

# Global Instance
config_manager = ConfigManager()
