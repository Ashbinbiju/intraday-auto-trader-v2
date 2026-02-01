"use client";
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { TrendingUp, Activity, PieChart, AlertCircle } from 'lucide-react';
import Link from 'next/link';

import { getBaseUrl } from '@/lib/api';
import MarketTicker from '@/components/MarketTicker';

export default function Dashboard() {
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [stats, setStats] = useState({ pnl: 0, winRate: 0, totalTrades: 0, wins: 0 });

    const fetchData = async () => {
        try {
            const baseUrl = getBaseUrl();
            const response = await axios.get(`${baseUrl}/data`);
            setData(response.data);
            calculateStats(response.data.positions || {});
        } catch (err) {
            console.error("Error fetching data", err);
        } finally {
            setLoading(false);
        }
    };

    const calculateStats = (positions: any) => {
        let totalPnl = 0;
        let wins = 0;
        let total = 0;

        Object.values(positions).forEach((pos: any) => {
            // Exclude Ghost Trades (never actually executed)
            if (pos.status === 'CLOSED' && pos.exit_reason !== 'RECONCILIATION_MISSING') {
                total++;
                const pnl = (pos.exit_price - pos.entry_price) * pos.qty;
                totalPnl += pnl;
                if (pnl > 0) wins++;
            }
        });

        setStats({
            pnl: totalPnl,
            winRate: total > 0 ? (wins / total) * 100 : 0,
            totalTrades: total,
            wins
        });
    };

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 1000); // Update every 1 second (was 3s)
        return () => clearInterval(interval);
    }, []);

    if (loading) return <div className="p-10 text-center">Loading Dashboard...</div>;

    const sectors = data?.top_sectors || [];

    return (
        <div className="space-y-8">
            {/* Header */}
            <header>
                <h1 className="text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-green-400 to-blue-500 mb-2">
                    Hello, Ashbin
                </h1>
                <p className="text-gray-400">Here is your market overview for today.</p>
            </header>

            {/* Market Indices Ticker */}
            <MarketTicker indices={data?.indices || []} />

            {/* Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <div className="bg-white/5 border border-white/10 p-6 rounded-2xl backdrop-blur-sm">
                    <div className="flex items-center gap-3 mb-2 text-gray-400">
                        <TrendingUp size={18} /> Today's P&L
                    </div>
                    <div className={`text-3xl font-bold ${stats.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {stats.pnl >= 0 ? '+' : ''}₹{stats.pnl.toFixed(2)}
                    </div>
                </div>

                <div className="bg-white/5 border border-white/10 p-6 rounded-2xl backdrop-blur-sm">
                    <div className="flex items-center gap-3 mb-2 text-gray-400">
                        <PieChart size={18} /> Win Rate
                    </div>
                    <div className="text-3xl font-bold text-blue-400">
                        {stats.winRate.toFixed(0)}%
                    </div>
                    <div className="text-xs text-gray-500 mt-1">{stats.wins} Wins / {stats.totalTrades} Trades</div>
                </div>

                <div className="bg-white/5 border border-white/10 p-6 rounded-2xl backdrop-blur-sm">
                    <div className="flex items-center gap-3 mb-2 text-gray-400">
                        <Activity size={18} /> Trades Taken
                    </div>
                    <div className="text-3xl font-bold text-purple-400">
                        {data?.total_trades_today || 0}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">Limit: {data?.limits?.max_trades_day || '-'}/Day</div>
                </div>

                <div className="bg-white/5 border border-white/10 p-6 rounded-2xl backdrop-blur-sm">
                    <div className="flex items-center gap-3 mb-2 text-gray-400">
                        <AlertCircle size={18} /> System Status
                    </div>
                    <div className={`text-xl font-bold ${data?.is_trading_allowed ? 'text-green-400' : 'text-red-400'}`}>
                        {data?.is_trading_allowed ? 'ACTIVE' : 'STOPPED'}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                        {data?.is_trading_allowed ? 'Scanning & Trading' : 'Kill Switch Active'}
                    </div>
                </div>
            </div>

            {/* Sector Heatmap & Recent Activity */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Heatmap */}
                <div className="col-span-2 bg-black/40 border border-white/10 rounded-2xl p-6">
                    <h3 className="text-xl font-bold mb-6 flex justify-between items-center">
                        Top Sectors Performance
                        <span className="text-xs bg-white/10 px-2 py-1 rounded text-gray-400">Live Scan</span>
                    </h3>
                    <div className="space-y-4">
                        {sectors.length > 0 ? sectors.map((sector: any, i: number) => (
                            <div key={i} className="group">
                                <div className="flex justify-between mb-1">
                                    <span className="font-bold text-gray-200">{sector.name}</span>
                                    <span className="text-green-400 font-mono">{sector.change}%</span>
                                </div>
                                <div className="h-3 bg-gray-800 rounded-full overflow-hidden">
                                    <div
                                        className="h-full bg-gradient-to-r from-green-600 to-green-400 transition-all duration-1000 group-hover:from-green-500 group-hover:to-green-300"
                                        style={{ width: `${Math.min(parseFloat(sector.change) * 20, 100)}%` }} // Visual scale
                                    ></div>
                                </div>
                            </div>
                        )) : (
                            <div className="text-center py-10 text-gray-500">No sector data available right now.</div>
                        )}
                    </div>
                </div>

                {/* Quick Actions / Recent Log */}
                <div className="space-y-6">
                    <div className="bg-gradient-to-br from-blue-900/20 to-black border border-blue-500/20 rounded-2xl p-6">
                        <h3 className="text-lg font-bold mb-4">Quick Actions</h3>
                        <div className="space-y-3">
                            <Link href="/trades" className="block w-full bg-blue-600/20 hover:bg-blue-600 border border-blue-500/40 text-center py-3 rounded-xl font-bold transition-all">
                                Manage Active Trades
                            </Link>
                            <Link href="/settings" className="block w-full bg-white/5 hover:bg-white/10 border border-white/10 text-center py-3 rounded-xl font-bold transition-all">
                                Configure Strategy
                            </Link>
                        </div>
                    </div>

                    <div className="bg-black/40 border border-white/10 rounded-2xl p-6">
                        <h3 className="text-lg font-bold mb-4">Recent Logs</h3>
                        <div className="space-y-2 font-mono text-xs text-gray-400">
                            {data?.logs?.slice(0, 3).map((log: string, i: number) => (
                                <div key={i} className="truncate border-b border-white/5 pb-1 last:border-0">
                                    {log}
                                </div>
                            ))}
                        </div>
                        <Link href="/logs" className="block mt-4 text-center text-blue-400 text-sm hover:underline">View All Logs</Link>
                    </div>
                </div>
            </div>
        </div>
    );
}
