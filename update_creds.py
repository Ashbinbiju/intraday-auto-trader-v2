from config import config_manager

def update_creds():
    print("Updating credentials...")
    
    # Ensure credentials section exists
    if "credentials" not in config_manager.config:
        config_manager.config["credentials"] = {}
        
    config_manager.config["credentials"]["dhan_client_id"] = "1107793529"
    config_manager.config["credentials"]["dhan_access_token"] = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzcwNDU3MDgwLCJpYXQiOjE3NzAzNzA2ODAsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTA3NzkzNTI5In0.rJ_lg7iN0uSVqMb5y4Mm1UamgyiMiIvHtezjBC2z0gZAOjn9o5-pZYREsX5sdTBWIniouUNEXBhHC2Xe05B-9g"
    config_manager.config["credentials"]["smart_api_api_key"] = "ruseeaBq" 
    
    config_manager.save_config()
    print("✅ Credentials updated and saved to Local + Remote.")
    
    # Verify
    print(f"Stored Token Length: {len(config_manager.config['credentials']['dhan_access_token'])}")

if __name__ == "__main__":
    update_creds()
