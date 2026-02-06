"use client";
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { ArrowRight, AlertCircle, CheckCircle, ChevronLeft, ChevronRight } from 'lucide-react';

import { getBaseUrl } from '@/lib/api';
import { useWebSocket } from '@/hooks/useWebSocket';
import { Signal } from '@/types';

export default function SignalsPage() {
    const [loading, setLoading] = useState(true);
    const [currentPage, setCurrentPage] = useState(1);
    const signalsPerPage = 20;

    const { data: wsData, isConnected } = useWebSocket();
    const [signals, setSignals] = useState<Signal[]>([]);

    const [audio] = useState(typeof Audio !== "undefined" ? new Audio('https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3') : null);

    useEffect(() => {
        if (wsData?.signals) {
            // Check if new signal arrived (simple length check)
            if (wsData.signals.length > signals.length && signals.length > 0) {
                // Play Sound
                audio?.play().catch(() => console.log("Audio play failed (interaction needed first)"));

                // Show Browser Notification (if supported)
                if ("Notification" in window && Notification.permission === "granted") {
                    new Notification("New Trade Signal!", { body: `New Signal Generated: ${wsData.signals[0].symbol}` });
                }
            }
            setSignals(wsData.signals);
            setLoading(false);
        }
    }, [wsData]);

    // Request Notification Permission on Mount
    useEffect(() => {
        if ("Notification" in window && Notification.permission !== "granted") {
            Notification.requestPermission();
        }
    }, []);

    // Pagination logic
    const totalPages = Math.ceil(signals.length / signalsPerPage);
    const startIndex = (currentPage - 1) * signalsPerPage;
    const endIndex = startIndex + signalsPerPage;
    const currentSignals = signals.slice(startIndex, endIndex);

    const goToNextPage = () => {
        if (currentPage < totalPages) setCurrentPage(currentPage + 1);
    };

    const goToPrevPage = () => {
        if (currentPage > 1) setCurrentPage(currentPage - 1);
    };

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
                        {currentSignals.map((signal, i) => (
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

            {/* Pagination Controls */}
            {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 bg-white/5 border border-white/10 rounded-xl">
                    <div className="text-sm text-gray-400">
                        Showing <span className="font-medium text-white">{startIndex + 1}</span> to{' '}
                        <span className="font-medium text-white">{Math.min(endIndex, signals.length)}</span> of{' '}
                        <span className="font-medium text-white">{signals.length}</span> signals
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={goToPrevPage}
                            disabled={currentPage === 1}
                            className="px-3 py-2 bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center gap-1"
                        >
                            <ChevronLeft size={16} />
                            Previous
                        </button>
                        <div className="px-4 py-2 bg-white/10 rounded-lg text-sm">
                            Page {currentPage} of {totalPages}
                        </div>
                        <button
                            onClick={goToNextPage}
                            disabled={currentPage === totalPages}
                            className="px-3 py-2 bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center gap-1"
                        >
                            Next
                            <ChevronRight size={16} />
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
