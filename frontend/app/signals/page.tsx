"use client";
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { ArrowRight, AlertCircle, CheckCircle } from 'lucide-react';

import { getBaseUrl } from '@/lib/api';
import { useWebSocket } from '@/hooks/useWebSocket';

export default function SignalsPage() {
    const [loading, setLoading] = useState(true);

    const { data: wsData, isConnected } = useWebSocket();
    const [signals, setSignals] = useState([]);

    useEffect(() => {
        if (wsData?.signals) {
            setSignals(wsData.signals);
            setLoading(false);
        }
    }, [wsData]);

    if (loading) return <div className="p-10 text-center text-gray-400 animate-pulse">Loading Live Signals...</div>;

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-600">
                    Live Signal Feed
                </h1>
                <div className="px-3 py-1 bg-blue-500/20 text-blue-400 text-xs rounded-full border border-blue-500/30">
                    {signals.length} Signals Generated
                </div>
            </div>

            <div className="bg-white/5 border border-white/10 rounded-xl overflow-x-auto backdrop-blur-sm">
                <table className="w-full text-left text-sm">
                    <thead className="bg-white/5 uppercase text-xs text-gray-400">
                        <tr>
                            <th className="px-6 py-4">Time</th>
                            <th className="px-6 py-4">Symbol</th>
                            <th className="px-6 py-4">Sector</th>
                            <th className="px-6 py-4">Price</th>
                            <th className="px-6 py-4">Message / Reason</th>
                            <th className="px-6 py-4">Action</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/10">
                        {signals.map((signal: any, i) => (
                            <tr key={i} className="hover:bg-white/5 transition-colors">
                                <td className="px-6 py-4 text-gray-400 font-mono">{signal.time.split(' ')[1]}</td>
                                <td className="px-6 py-4 font-bold text-white">{signal.symbol}</td>
                                <td className="px-6 py-4 text-gray-400">{signal.sector}</td>
                                <td className="px-6 py-4 font-mono text-green-400">₹{signal.price}</td>
                                <td className="px-6 py-4">
                                    <div className="flex items-center gap-2">
                                        <CheckCircle size={14} className="text-green-500" />
                                        <span>{signal.message}</span>
                                    </div>
                                </td>
                                <td className="px-6 py-4">
                                    <span className="inline-flex items-center gap-1 px-2 py-1 bg-green-500/20 text-green-400 text-xs rounded border border-green-500/30">
                                        BUY SIGNAL
                                    </span>
                                </td>
                            </tr>
                        ))}
                        {signals.length === 0 && !loading && (
                            <tr>
                                <td colSpan={6} className="px-6 py-12 text-center text-gray-500">
                                    <AlertCircle className="mx-auto mb-2 opacity-50" size={32} />
                                    No signals generated yet today.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
