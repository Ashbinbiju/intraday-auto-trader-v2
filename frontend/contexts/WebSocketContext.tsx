"use client";
import React, { createContext, useContext, useState, useEffect, useRef, ReactNode } from 'react';
import { getWsUrl, getBaseUrl } from '@/lib/api';
import axios from 'axios';
import { MarketData } from '@/types';

interface WebSocketContextType {
    data: MarketData | null;
    isConnected: boolean;
}

const WebSocketContext = createContext<WebSocketContextType>({
    data: null,
    isConnected: false
});

export function WebSocketProvider({ children }: { children: ReactNode }) {
    const [data, setData] = useState<MarketData | null>(null);
    const [isConnected, setIsConnected] = useState(false);
    const ws = useRef<WebSocket | null>(null);
    const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

    useEffect(() => {
        // Initial Fetch
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
            // Prevent multiple connections
            if (ws.current && (ws.current.readyState === WebSocket.OPEN || ws.current.readyState === WebSocket.CONNECTING)) {
                console.log("WebSocket already connected/connecting. Skipping.");
                return;
            }

            const url = getWsUrl();
            const socket = new WebSocket(url);
            ws.current = socket;

            socket.onopen = () => {
                console.log("✅ WebSocket Connected");
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
                console.log("WebSocket Disconnected. Retrying in 3s...");
                setIsConnected(false);
                ws.current = null;

                // Clear any existing timeout
                if (reconnectTimeoutRef.current) {
                    clearTimeout(reconnectTimeoutRef.current);
                }

                // Only reconnect if document is visible
                if (!document.hidden) {
                    reconnectTimeoutRef.current = setTimeout(connect, 3000);
                }
            };

            socket.onerror = (err) => {
                console.warn("WebSocket Error", err);
                socket.close();
            };
        };

        // Initial Connect
        connect();

        // Reconnect on Tab Focus
        const handleVisibilityChange = () => {
            if (document.visibilityState === 'visible') {
                console.log("Tab Active: Checking WebSocket...");
                connect();
            } else {
                // Clear reconnect timeout when tab is hidden
                if (reconnectTimeoutRef.current) {
                    clearTimeout(reconnectTimeoutRef.current);
                    reconnectTimeoutRef.current = null;
                }
            }
        };

        document.addEventListener("visibilitychange", handleVisibilityChange);

        return () => {
            document.removeEventListener("visibilitychange", handleVisibilityChange);
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
            }
            if (ws.current) {
                ws.current.close();
            }
        };
    }, []); // Empty deps - run once

    return (
        <WebSocketContext.Provider value={{ data, isConnected }}>
            {children}
        </WebSocketContext.Provider>
    );
}

export function useWebSocketContext() {
    return useContext(WebSocketContext);
}
