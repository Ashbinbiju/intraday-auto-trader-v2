"""
Quick script to sync local config.json to Supabase remote config.
Run this to update the Render deployment with your latest settings.
"""
from config import config_manager
import json

# Load current local config
with open("config.json", "r") as f:
    local_config = json.load(f)

print("📤 Syncing config to Supabase...")
print(f"Leverage setting: {local_config.get('position_sizing', {}).get('leverage_equity', 'NOT FOUND')}")

# Save to Supabase
config_manager.save_config()

print("✅ Config synced successfully!")
print("\n🔄 Render will use these settings on next deployment/restart")
