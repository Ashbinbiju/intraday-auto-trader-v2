import { useState, useEffect, useRef } from 'react';
import { getWsUrl } from '@/lib/api';

export function useWebSocket() {
    const [data, setData] = useState<any>(null);
    const [isConnected, setIsConnected] = useState(false);
    const ws = useRef<WebSocket | null>(null);

    useEffect(() => {
        const connect = () => {
            if (ws.current) return;

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
                setTimeout(connect, 3000); // Retry after 3s
            };

            socket.onerror = (err) => {
                console.warn("WebSocket Connection Issue (Retrying...)", err);
                socket.close();
            };
        };

        connect();

        return () => {
            if (ws.current) {
                ws.current.close();
            }
        };
    }, []);

    return { data, isConnected };
}
