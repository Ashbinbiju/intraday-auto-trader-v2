import json
import os
import logging

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
        "trading_start_time": "09:30",
        "trading_end_time": "14:45"
    },
    "general": {
        "quantity": 1,
        "check_interval": 300,       # 5 minutes
        "dry_run": True
    }
}

class ConfigManager:
    def __init__(self):
        self.config = DEFAULT_CONFIG.copy()
        self.load_config()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    saved_config = json.load(f)
                    # Merge saved config with default (for new keys)
                    self.update_nested(self.config, saved_config)
            except Exception as e:
                logging.error(f"Error loading config: {e}")
        else:
            self.save_config()

    def update_nested(self, d, u):
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = self.update_nested(d.get(k, {}), v)
            else:
                d[k] = v
        return d

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving config: {e}")

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
        self.save_config()

# Global Instance
config_manager = ConfigManager()
