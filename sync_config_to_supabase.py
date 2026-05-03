import json

# 1. Load current local config BEFORE importing anything that might overwrite it
with open("config.json", "r") as f:
    local_config = json.load(f)

from config import config_manager

# Update config manager with local config using deep merge
config_manager.update_nested(config_manager.config, local_config)
print(f"DEBUG: Broker in config_manager is {config_manager.config['general']['broker']}")

# Save to Supabase
config_manager.save_config()

print("✅ Config synced successfully!")
print("\n🔄 Render will use these settings on next deployment/restart")
