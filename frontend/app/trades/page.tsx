"use client";
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Shield, Target, TrendingUp, XCircle, AlertTriangle, Wifi, WifiOff, CheckCircle } from 'lucide-react';
import { useWebSocket } from '@/hooks/useWebSocket';

import { getBaseUrl } from '@/lib/api';

export default function TradesPage() {
    const { data: wsData, isConnected } = useWebSocket();
    const [localData, setLocalData] = useState<any>(null);
    const [processing, setProcessing] = useState<string | null>(null);

    // Sync WS data to local state
    useEffect(() => {
        if (wsData) {
            setLocalData(wsData);
        }
    }, [wsData]);

    const handleManualExit = async (symbol: string) => {
        if (!confirm(`Are you sure you want to FORCE EXIT ${symbol}?`)) return;
        setProcessing(symbol);
        try {
            const baseUrl = getBaseUrl();
            await axios.post(`${baseUrl}/trade/close/${symbol}`);
            alert(`Exit Order Placed for ${symbol}`);
            // No need to fetch, WS will update
        } catch (err) {
            alert(`Failed to exit ${symbol}`);
        } finally {
            setProcessing(null);
        }
    };

    const toggleKillSwitch = async () => {
        const isAllowed = localData?.is_trading_allowed;
        const action = isAllowed ? 'kill-switch' : 'resume';
        if (!confirm(`Are you sure you want to ${isAllowed ? 'STOP' : 'RESUME'} all trading?`)) return;

        try {
            const baseUrl = getBaseUrl();
            await axios.post(`${baseUrl}/bot/${action}`);
            // WS update will reflect change
        } catch (err) {
            alert("Failed to toggle Kill Switch");
        }
    };

    if (!localData && !isConnected) return <div className="p-10 text-center text-gray-400 animate-pulse">Connecting to Live Feed...</div>;

    // Fallback if connected but no data yet (rare)
    const displayData = localData || {};

    const positions = displayData?.positions ? Object.entries(displayData.positions).filter(([_, p]: any) => p.status === "OPEN") : [];

    return (
        <div className="space-y-8">
            {/* Header & Kill Switch */}
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center rounded-2xl bg-gradient-to-r from-red-900/20 to-black p-6 border border-red-500/10 relative overflow-hidden gap-4">
                <div>
                    <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
                        Position Manager
                        {isConnected ? <Wifi className="text-green-500 animate-pulse" size={20} /> : <WifiOff className="text-red-500" size={20} />}
                    </h1>
                    <p className="text-gray-400">Real-Time WebSocket Feed</p>
                </div>

                <button
                    onClick={toggleKillSwitch}
                    className={`w-full md:w-auto flex items-center justify-center gap-3 px-6 py-3 rounded-xl font-bold border transition-all ${displayData?.is_trading_allowed
                        ? 'bg-red-500/10 border-red-500 text-red-500 hover:bg-red-500 hover:text-white'
                        : 'bg-green-500/10 border-green-500 text-green-500 hover:bg-green-500 hover:text-white'
                        }`}
                >
                    {displayData?.is_trading_allowed ? (
                        <><XCircle size={24} /> STOP TRADING (KILL SWITCH)</>
                    ) : (
                        <><CheckCircle size={24} /> RESUME TRADING</>
                    )}
                </button>
            </div>

            {!displayData?.is_trading_allowed && (
                <div className="bg-yellow-500/10 border border-yellow-500 text-yellow-400 p-4 rounded-xl flex items-center justify-center gap-2 text-center">
                    <AlertTriangle />
                    <span>
                        <span className="font-bold">Trading Paused (Kill Switch Active).</span>
                        <br className="md:hidden" /> New entries are blocked.
                    </span>
                </div>
            )}

            {/* Active Positions Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {positions.map(([symbol, pos]: any) => {
                    return (
                        <Card key={symbol} symbol={symbol} pos={pos} handleManualExit={handleManualExit} processing={processing} />
                    );
                })}
            </div>

            {positions.length === 0 && (
                <div className="text-center py-20 text-gray-600">
                    <TrendingUp size={48} className="mx-auto mb-4 opacity-20" />
                    <p>No active positions. Waiting for signals...</p>
                </div>
            )}
        </div>
    );
}

// Sub-components to keep code clean and fix the TimeCounter scope issue
function Card({ symbol, pos, handleManualExit, processing }: any) {
    const entry = pos.entry_price || 0;
    const sl = pos.sl || 0;
    const tp = pos.target || 0;
    const currentLtp = pos.current_ltp || entry;

    // Calculate unrealized P&L
    const unrealizedPnl = (currentLtp - entry) * (pos.qty || 0);
    const pnlPct = entry > 0 ? ((currentLtp - entry) / entry) * 100 : 0;
    const isProfitable = unrealizedPnl >= 0;

    return (
        <div className="bg-white/5 border border-white/10 rounded-xl p-6 relative overflow-hidden group hover:border-blue-500/30 transition-all">
            <div className="absolute top-0 left-0 w-1 h-full bg-blue-500"></div>

            {/* Grade Badge */}
            {pos.setup_grade && (
                <div className={`absolute top-0 right-0 px-3 py-1 text-xs font-bold rounded-bl-xl ${pos.setup_grade === 'A+' ? 'bg-purple-500 text-white' :
                    pos.setup_grade === 'A' ? 'bg-green-500 text-black' :
                        pos.setup_grade === 'ORPHAN' ? 'bg-yellow-500 text-black border-l-2 border-b-2 border-yellow-700' :
                            'bg-blue-500 text-white'
                    }`}>
                    {pos.setup_grade === 'ORPHAN' ? '⚠️ ORPHAN / IMPORTED' : `${pos.setup_grade} Setup`}
                </div>
            )}

            <div className="flex justify-between items-start mb-6 mt-2">
                <div>
                    <h3 className="text-2xl font-bold">{symbol}</h3>
                    <div className="text-sm text-gray-400 flex items-center gap-2">
                        Entered at {pos.entry_time}
                        <span className="text-gray-600">|</span>
                        <TimeCounter startTime={pos.entry_time} />
                    </div>
                </div>
                <div className="text-right mt-4 space-y-1">
                    {/* Current LTP */}
                    <div className={`text-2xl font-mono font-bold ${isProfitable ? 'text-green-400' : 'text-red-400'}`}>
                        ₹{currentLtp.toFixed(2)}
                    </div>
                    <div className="text-xs text-gray-500">Current Price</div>

                    {/* Unrealized P&L */}
                    <div className={`text-sm font-mono font-semibold ${isProfitable ? 'text-green-400' : 'text-red-400'}`}>
                        {isProfitable ? '+' : ''}₹{unrealizedPnl.toFixed(2)} ({isProfitable ? '+' : ''}{pnlPct.toFixed(2)}%)
                    </div>

                    {/* Entry Price (smaller, below) */}
                    <div className="text-xs text-gray-500 mt-2">Entry: ₹{entry.toFixed(2)}</div>
                </div>
            </div>

            {/* Progress Visual */}
            <div className="relative h-2 bg-gray-700 rounded-full mb-6 mt-4">
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-red-500 rounded-full shadow-[0_0_10px_red]" title={`SL: ${sl.toFixed(2)}`}></div>
                <div className="absolute left-1/3 top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full z-10" title="Entry"></div>
                <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-green-500 rounded-full shadow-[0_0_10px_lime]" title={`TP: ${tp.toFixed(2)}`}></div>
            </div>

            <div className="flex justify-between text-xs text-gray-400 mb-6 font-mono">
                <span className="text-red-400 flex items-center gap-1"><Shield size={12} /> {sl.toFixed(2)}</span>
                <span className="text-green-400 flex items-center gap-1"><Target size={12} /> {tp.toFixed(2)}</span>
            </div>

            <div className="grid grid-cols-2 gap-3">
                <div className="bg-black/40 p-3 rounded-lg flex flex-col justify-center items-center border border-white/5">
                    <span className="text-gray-500 text-xs uppercase">Quantity</span>
                    <span className="font-bold text-lg">{pos.qty}</span>
                </div>
                <button
                    onClick={() => handleManualExit(symbol)}
                    disabled={processing === symbol}
                    className="bg-red-500/10 hover:bg-red-600 hover:text-white border border-red-500/50 text-red-500 rounded-lg font-bold transition-all flex items-center justify-center gap-2"
                >
                    {processing === symbol ? 'Exiting...' : 'EXIT NOW'}
                </button>
            </div>
        </div>
    )
}

function TimeCounter({ startTime }: { startTime: string }) {
    const [duration, setDuration] = useState("");

    useEffect(() => {
        const calc = () => {
            const now = new Date();
            const [h, m] = startTime.split(':').map(Number);
            const start = new Date();
            start.setHours(h, m, 0);
            const diffMs = now.getTime() - start.getTime();
            if (diffMs < 0) return setDuration("Just Now");
            const mins = Math.floor(diffMs / 60000);
            const secs = Math.floor((diffMs % 60000) / 1000);
            setDuration(`${mins}m ${secs}s`);
        };
        calc();
        const i = setInterval(calc, 1000);
        return () => clearInterval(i);
    }, [startTime]);

    return <span className="font-mono text-yellow-400">{duration}</span>;
}
