export const getBaseUrl = () => {
    if (typeof window === 'undefined') return 'http://localhost:8000'; // SSR

    // Check if configured via env (e.g. production)
    if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;

    // Dynamic LAN detection
    const protocol = window.location.protocol;
    const host = window.location.hostname; // 'localhost' or '192.168.x.x'
    return `${protocol}//${host}:8000`;
};

export const getWsUrl = () => {
    if (typeof window === 'undefined') return 'ws://localhost:8000/ws';

    if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    return `${protocol}//${host}:8000/ws`;
};
