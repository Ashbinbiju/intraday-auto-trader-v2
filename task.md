# Task List

- [x] **Core Bot & Initial UI (v1.0)** <!-- id: 100 -->
    - [x] Scraper, SmartAPI, Indicators, Logic, Basic API, Basic Dashboard.

- [x] **Backend Upgrade (v2.0)** <!-- id: 29 -->
    - [x] **Settings API**: Endpoint to GET/POST config (Risk, Limits, Timings) <!-- id: 30 -->
    - [x] **Trade Management API**: Endpoints to Close Position, Kill Switch <!-- id: 31 -->
    - [x] **Enhanced Logging**: Structured logs (Scan, Signal, Order, Error) exposed via API <!-- id: 32 -->
    - [x] **Metrics Engine**: Calculate P&L, Win Rate (Today) <!-- id: 33 -->
    - [x] **Holiday/Weekend Check**: Prevent bot from running on non-trading days <!-- id: 45 -->

- [x] **Robustness & Reliability** <!-- id: 50 -->
    - [x] **Order Reconciliation**: Sync `BOT_STATE` with Broker (`/maxOrders`, `/position`) to fix ghost trades <!-- id: 51 -->
    - [x] **Intent Logging**: Log "WHY" a trade was skipped (e.g., "Price below VWAP") <!-- id: 52 -->
    - [x] **Rate Limiting**: Throttled Position Manager (5 req/sec) and configured Retry Logic to prevent API bans.
    - [x] **Real-Time Order Updates**: Integrated "Smart Order Update" WebSocket to bypass polling latency.
    - [x] **Margin Calculator**: Added `/tool/margin` endpoint to check required margin for positions.
    - [x] **Postback Webhook**: Added `/webhook/angel-one` to support HTTPS postbacks from Angel One.
    - [x] **Portfolio APIs**: Added endpoints for Holdings (`/portfolio/holdings`) and Conversion (`/portfolio/convert`).
    - [x] **Brokerage Calculator**: Added `/tool/brokerage` endpoint to estimate charges before trading.
    - [x] **Order APIs**: Added endpoints for Place, Modify, Cancel, Books, and LTP (`/order/*`).
    - [x] **Error Handling**: Implemented Error Map (`AG8001` -> "Invalid Token") for clear debugging logs.
    - [x] **API Audit**: Verified Response Structure and patched `status` check to handle boolean/string inconsistency.
    - [x] **Dashboard Sync**: Fixed issue where "Max Trades/Day" setting was not reflected in the Dashboard UI.
    - [x] **Limit Display Fix**: Initialized `BOT_STATE['limits']` to prevent "Limit: -/Day" on startup.
    - [x] **Config Sync**: Ensured `main.py` initialization uses saved config values instead of hardcoded defaults.
    - [x] **Instant Sync**: Patched `POST /settings` to broadcast changes immediately via WebSocket, bypassing bot loop delay.
    - [x] **UI Polish**: Renamed "Live Scrape" badge to "Live Scan" on Dashboard for clarity.
    - [x] **Trading Guard**: Implemented `trading_start_time` (Default: 9:30 AM) to skip the first 15m of volatility.
    - [x] **Settings UI**: Added "Trading Start Time" input to Settings page.

- [x] **System Audit & Polish** <!-- id: 40 -->
    - [x] **Code Cleanup**: Removed unused imports (`ws_hub.py`) and verified module integrity. <!-- id: 41 -->
    - [x] **Logic Verification**: Confirmed robustness of `indicators.py` and API error handling. <!-- id: 42 -->
    - [x] **Frontend QA**: Added loading states to `Signals` & `Journal` pages. Refactored both to use WebSocket! <!-- id: 43 -->
    - [x] **Security Check**: Verified no sensitive data leakage in logs. (Note: API Credentials remain hardcoded in `smart_api_helper.py` as per current config). <!-- id: 44 -->

- [x] **Critical: Persistence Logic** <!-- id: 50 -->
    - [x] **State Manager**: Implemented `state_manager.py` for JSON-based backsups. <!-- id: 51 -->
    - [x] **Main Loop**: Integrated `load_state` on start and `save_state` on Entry/Exit. <!-- id: 52 -->
    - [x] **API Persistence**: Integrated `save_state` on all configuration and manual override endpoints. <!-- id: 53 -->

- [x] **Startup Reconciliation** <!-- id: 60 -->
    - [x] **Backend Logic**: Implemented `reconcile_state()` to sync Broker -> Bot. <!-- id: 61 -->
    - [x] **Orphan Handling**: Detects trades that exist in Broker but not in Bot. <!-- id: 62 -->
    - [x] **UI Indicators**: Badge orphaned trades in `TradesPage` & `JournalPage`. <!-- id: 63 -->

- [x] **Frontend Upgrade (v2.0)** <!-- id: 34 -->
    - [x] **Layout**: Implement Sidebar Navigation (Dashboard, Signals, Trades, Journal, Settings, Logs) <!-- id: 35 -->
    - [x] **Dashboard Home**: P&L Cards, Win Rate, Sector Heatmap <!-- id: 36 -->
    - [x] **Live Signals**: Detailed Table (Reason: VWAP/EMA, Status: Entered/Skipped) <!-- id: 37 -->
    - [x] **Active Trades**: Position Manager Cards with Progress Bar & Exit Button <!-- id: 38 -->
    - [x] **Settings Page**: Form to control Bot Config (SL, TP, Limits) <!-- id: 39 -->
    - [x] **Logs Page**: Tabbed Log Viewer (Scan, Signal, Error) <!-- id: 40 -->

    - [x] **Active Trades**: Added "Time Active" counter and "Setup Grade" badge <!-- id: 53 -->
    - [x] **Trade Journal**: Added "Auto Grade" (A+/A/B) and "Exit Reason" columns <!-- id: 54 -->

- [x] **Final Verification** <!-- id: 41 -->
    - [x] **Git Sync**: Sync local environment with remote changes (Pull Request) <!-- id: 64 -->
    - [x] **WebSocket Migration**: Replaced polling with instant WS updates <!-- id: 55 -->
    - [x] **Mobile Optimization**: Fixed layout overflow, added Bottom Navigation Bar <!-- id: 56 -->
    - [x] **Fix Control Panel Latency**: Async Broadcast for instant Kill Switch/Resume/Exit updates.
    - [x] **Exit Strategy Upgrade**:
        - [x] Breakeven Lock (+1R Trigger).
        - [x] Dual Confirmation (Close < EMA20 AND Close < VWAP).
        - [x] Time-Based Stagnation Exit (> 60m). Implemented `AsyncScanner` (aiohttp) to reduce market scan time from ~12m to <60s. <!-- id: 46 -->
    - [x] Verify End-to-End Flow (Config -> Bot -> Trade -> Exit) <!-- id: 42 -->
- [x] **SmartAPI Index Data** <!-- id: 70 -->
    - [x] Verify `ltpData` for 26000/26009
    - [x] Implement Sentinel Logic (Range Position > 0.55)
    - [x] Expand Scanner to Top 4 Sectors
    - [x] Implement Local High/Low Cache (`index_memory`)
    - [x] Integrate Reliable Index API (`brkpoint.in`)

- [x] **System Reliability & Documentation** <!-- id: 71 -->
    - [x] Fix `start_time` Loop Crash
    - [x] Implement Granular Logging (Regime, Entry Guard)
    - [x] Update Holiday Calendar (2026)
    - [x] Create Strategy Note (`strategy_summary.md`)
    - [x] Update Holiday Calendar (2026)
    - [x] Create Strategy Note (`strategy_summary.md`)
    - [x] Create API Risk Analysis (`api_risk_analysis.md`)

- [/] **Debugging & Verification** <!-- id: 72 -->
    - [x] Investigate "Zero Signals" (Confirmed Rate Limit & Syntax Error)
    - [x] Enable Global Debug Logging (`async_scanner.py`)
    - [x] Implement Rate Limiting (3 req/s)
    - [x] Fix Syntax Error in Helper
    - [x] Fix Data Fetching Issues (Verified via Script)
    - [x] Standardize API Logic (The Definitive Fix for "Invalid Token")
    - [x] Fix RSI KeyError in async_scanner.py
    - [x] Fix Ghost Trade P&L Bug (Exclude RECONCILIATION_MISSING from metrics)
    - [x] Fix Missing Target Field Bug (Positions were created without take-profit)
    - [x] Fix Pandas Import (Position management was crashing)
    - [x] Fix Paper Trade Reconciliation (Skip broker API calls in dry_run mode)
    - [x] Fix Trades Page Crashes (CheckCircle import + toFixed() safety checks)
    - [ ] Analyze Rejection Logs


