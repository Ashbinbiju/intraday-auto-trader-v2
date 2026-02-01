"use client";
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { BookOpen } from 'lucide-react';
import { useWebSocket } from '@/hooks/useWebSocket';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function JournalPage() {
    const [trades, setTrades] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const { data: wsData } = useWebSocket();

    useEffect(() => {
        if (wsData?.positions) {
            const allPositions = wsData.positions;
            const closedTrades = Object.entries(allPositions)
                .map(([symbol, data]: any) => ({ symbol, ...data }))
                .filter((p: any) =>
                    p.status === "CLOSED" &&
                    p.exit_reason !== 'RECONCILIATION_MISSING' && // Exclude ghost trades
                    p.exit_price &&
                    p.exit_price > 0 // Exclude invalid exit prices
                );
            setTrades(closedTrades.reverse());
            setLoading(false);
        }
    }, [wsData]);

    if (loading) return <div className="p-10 text-center text-gray-400 animate-pulse">Loading Trade History...</div>;

    return (
        <div className="space-y-6">
            <h1 className="text-3xl font-bold text-white flex items-center gap-3">
                <BookOpen className="text-purple-400" /> Trade Journal
            </h1>

            <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden backdrop-blur-sm">
                <table className="w-full text-left text-sm">
                    <thead className="bg-white/5 uppercase text-xs text-gray-400">
                        <tr>
                            <th className="px-6 py-4">Symbol</th>
                            <th className="px-6 py-4">Grade</th>
                            <th className="px-6 py-4">Entry Time</th>
                            <th className="px-6 py-4">Entry Price</th>
                            <th className="px-6 py-4">Exit Price</th>
                            <th className="px-6 py-4">P&L %</th>
                            <th className="px-6 py-4">Reason</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/10">
                        {trades.map((trade: any, i) => {
                            const pnl = ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100;
                            const isWin = pnl > 0;

                            return (
                                <tr key={i} className="hover:bg-white/5 transition-colors">
                                    <td className="px-6 py-4 font-bold text-white max-w-[200px] truncate">{trade.symbol}</td>
                                    <td className="px-6 py-4">
                                        {trade.setup_grade && (
                                            <span className={`px-2 py-1 text-xs font-bold rounded ${trade.setup_grade === 'A+' ? 'bg-purple-500/20 text-purple-400 border border-purple-500/50' :
                                                trade.setup_grade === 'A' ? 'bg-green-500/20 text-green-400 border border-green-500/50' :
                                                    trade.setup_grade === 'ORPHAN' ? 'bg-yellow-500/20 text-yellow-500 border border-yellow-500/50' :
                                                        'bg-blue-500/20 text-blue-400 border border-blue-500/50'
                                                }`}>
                                                {trade.setup_grade}
                                            </span>
                                        )}
                                    </td>
                                    <td className="px-6 py-4 text-gray-400">{trade.entry_time}</td>
                                    <td className="px-6 py-4 font-mono">₹{trade.entry_price}</td>
                                    <td className="px-6 py-4 font-mono">₹{trade.exit_price}</td>
                                    <td className={`px-6 py-4 font-bold ${isWin ? 'text-green-400' : 'text-red-400'}`}>
                                        {isWin ? '+' : ''}{pnl.toFixed(2)}%
                                    </td>
                                    <td className="px-6 py-4 text-xs uppercase tracking-wider text-gray-500">
                                        {trade.exit_reason || "AUTO"}
                                    </td>
                                </tr>
                            );
                        })}
                        {trades.length === 0 && !loading && (
                            <tr>
                                <td colSpan={6} className="px-6 py-12 text-center text-gray-500">
                                    No closed trades recorded yet.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
