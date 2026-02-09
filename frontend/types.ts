export interface Position {
    status: string;
    entry_price: number;
    sl: number;
    target: number;
    current_ltp: number;
    qty: number;
    setup_grade?: string;
    entry_time: string;
    message?: string;
}

export interface Signal {
    symbol: string;
    time: string;
    sector: string;
    price: number;
    message: string;
}

export interface MarketData {
    is_trading_allowed: boolean;
    positions: Record<string, Position>;
    signals: Signal[];
    last_heartbeat?: number;
}
