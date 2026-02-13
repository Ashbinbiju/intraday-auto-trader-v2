import { useState, useEffect, useRef } from 'react';
import { getWsUrl, getBaseUrl } from '@/lib/api';
import axios from 'axios';

import { MarketData } from '@/types';

export function useWebSocket() {
    const [data, setData] = useState<MarketData | null>(null);
    const [isConnected, setIsConnected] = useState(false);
    const ws = useRef<WebSocket | null>(null);

    useEffect(() => {
        // Initial Fetch (Fix for navigation reset)
        const fetchInitialState = async () => {
            try {
                const baseUrl = getBaseUrl();
                const res = await axios.get(`${baseUrl}/data`);
                if (res.data) {
                    console.log("Initial State Fetched (HTTP)", res.data);
                    setData(res.data);
                }
            } catch (e) {
                console.error("Failed to fetch initial state", e);
            }
        };
        fetchInitialState();

        const connect = () => {
            // Prevent multiple connections: Check if socket exists and is OPEN or CONNECTING
            if (ws.current && (ws.current.readyState === WebSocket.OPEN || ws.current.readyState === WebSocket.CONNECTING)) {
                console.log("WebSocket already connected/connecting. Skipping.");
                return;
            }

            const url = getWsUrl();
            const socket = new WebSocket(url);
            ws.current = socket;

            socket.onopen = () => {
                console.log("WebSocket Connected");
                setIsConnected(true);
            };

            socket.onmessage = (event) => {
                try {
                    const parsed = JSON.parse(event.data);
                    setData(parsed);
                } catch (e) {
                    console.error("Failed to parse WS message", e);
                }
            };

            socket.onclose = () => {
                console.log("WebSocket Disconnected. Retrying...");
                setIsConnected(false);
                ws.current = null;
                // Only set timeout if document is visible, otherwise wait for visibility change
                if (!document.hidden) {
                    setTimeout(connect, 3000);
                }
            };

            socket.onerror = (err) => {
                console.warn("WebSocket Connection Issue", err);
                socket.close();
            };
        };

        // Initial Connect
        connect();

        // ------------------------------------------
        // Reconnect on Tab Focus (Instant updates)
        // ------------------------------------------
        const handleVisibilityChange = () => {
            if (document.visibilityState === 'visible') {
                console.log("Tab Active: Checking WebSocket...");
                // connect() now has proper guard, safe to call
                connect();
            }
        };

        document.addEventListener("visibilitychange", handleVisibilityChange);

        return () => {
            document.removeEventListener("visibilitychange", handleVisibilityChange);
            if (ws.current) {
                ws.current.close();
            }
        };
    }, []);

    return { data, isConnected };
}
