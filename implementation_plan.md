# WebSocket Order Status Integration

## Goal
Replace polling/latency with real-time order updates (Filled, Rejected, Cancelled) using Angel One's "Smart Order Update" WebSocket.

## Components

### 1. `smart_websocket.py` (New File)
- **Library**: `websockets` (Async).
- **Class**: `OrderUpdateWS`
- **Functionality**:
    - Connects to `wss://tns.angelone.in/smart-order-update`
    - Authorization Header: `Bearer {jwtToken}`
    - Heartbeat: Ping every 10s.
    - Message Handling:
        - `AB05` (Complete): Update position setup/status.
        - `AB03` (Rejected) / `AB02` (Cancelled): Log warning, update active order tracking.

### 2. `api.py` Integration
- **Startup**: Launch a background async task `start_order_update_ws`.
- **Session Handling**: The task must wait until `SMART_API_SESSION` is initialized (by `main.py` thread).
- **State Update**: Directly modify `BOT_STATE` (shared memory).

## Flow
1. API starts.
2. BG Task checks `main.SMART_API_SESSION`.
3. Once logged in, extracts `jwtToken`.
4. Connects WS.
5. On Order Update -> Update `BOT_STATE['positions']`.
   - If "Filled" -> Update `status="OPEN"` (if pending) or just ensure `entry_price` is accurate?
   - Wait, `main.py` manages positions. If an order is filled, `main.py` usually knows because it placed it.
   - **Crucial Value**: Knowing when **Target/SL exit orders** are filled instantly.
   - When SL Limit/Market is filled, `management_positions` might take 0.2-1.5s to see it via generic polling. WS will trigger **instant** state update using `broadcast()`.

## Risks
- **Token Expiry**: JWT might expire. Need logic to reconnect/refresh (or just restart bot).
- **Connection Limit**: 3 connections max. We only use 1.

## UX Improvement
- Faster "Position Closed" updates.
- Real-time "Filled" notifications.
