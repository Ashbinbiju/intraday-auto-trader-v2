"use client";
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { BookOpen, Calendar, TrendingUp, TrendingDown, DollarSign, Activity, X } from 'lucide-react';
import {
    startOfMonth,
    endOfMonth,
    eachDayOfInterval,
    format,
    parseISO,
    isSameDay,
    getDay,
    addDays,
    subMonths,
    addMonths
} from 'date-fns';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function JournalPage() {
    const [trades, setTrades] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [currentMonth, setCurrentMonth] = useState(new Date());
    const [selectedTrade, setSelectedTrade] = useState<any>(null);
    const [selectedDay, setSelectedDay] = useState<Date | null>(null);

    useEffect(() => {
        fetchHistory();
    }, []);

    const fetchHistory = async () => {
        try {
            setLoading(true);
            const res = await axios.get(`${API_URL}/api/trades/history`);
            if (res.data?.trades) {
                setTrades(res.data.trades);
            }
        } catch (error) {
            console.error("Failed to fetch history:", error);
        } finally {
            setLoading(false);
        }
    };

    // --- Statistics Calculation ---
    // Filter trades for the selected month to show relevant stats
    const monthTrades = trades.filter(t => {
        const date = parseISO(t.entry_time);
        return date.getMonth() === currentMonth.getMonth() &&
            date.getFullYear() === currentMonth.getFullYear();
    });

    const totalPnL = monthTrades.reduce((acc, t) => acc + (t.pnl || 0), 0);
    const winRate = monthTrades.length > 0
        ? ((monthTrades.filter(t => (t.pnl || 0) > 0).length / monthTrades.length) * 100).toFixed(1)
        : "0.0";
    const tradeCount = monthTrades.length;

    // --- Calendar Logic ---
    const monthStart = startOfMonth(currentMonth);
    const monthEnd = endOfMonth(currentMonth);
    const startDate = subMonths(monthStart, 0); // Logic hook if we want to show prev month overflow? No, stick to current.

    // Create grid days
    const daysInMonth = eachDayOfInterval({ start: monthStart, end: monthEnd });

    // Calculate P&L for each day
    const getDayData = (day: Date) => {
        const dayTrades = trades.filter(t => isSameDay(parseISO(t.entry_time), day));
        const dailyPnL = dayTrades.reduce((acc, t) => acc + (t.pnl || 0), 0);
        return {
            trades: dayTrades,
            pnl: dailyPnL,
            count: dayTrades.length
        };
    };

    // Padding for start of month (Monday start? No, Sunday start usually)
    const startDay = getDay(monthStart); // 0 = Sunday
    const emptyDays = Array(startDay).fill(null);

    return (
        <div className="space-y-6 max-w-[1400px] mx-auto pb-10">
            {/* Header & Stats */}
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                <div>
                    <h1 className="text-3xl font-bold text-white flex items-center gap-3">
                        <BookOpen className="text-purple-400" /> Trade Journal
                    </h1>
                    <p className="text-gray-400 text-sm mt-1">Review your performance history</p>
                </div>

                {/* Monthly Stats Cards */}
                <div className="flex gap-4 w-full md:w-auto">
                    <div className={`flex-1 md:w-40 p-4 rounded-xl border ${totalPnL >= 0 ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
                        <div className="text-gray-400 text-xs uppercase font-bold flex items-center gap-2">
                            <DollarSign size={14} /> Monthly P&L
                        </div>
                        <div className={`text-2xl font-bold mt-1 ${totalPnL >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {totalPnL >= 0 ? '+' : ''}₹{totalPnL.toFixed(2)}
                        </div>
                    </div>

                    <div className="flex-1 md:w-32 p-4 rounded-xl border bg-blue-500/10 border-blue-500/30">
                        <div className="text-gray-400 text-xs uppercase font-bold flex items-center gap-2">
                            <Activity size={14} /> Win Rate
                        </div>
                        <div className="text-2xl font-bold mt-1 text-blue-400">
                            {winRate}%
                        </div>
                    </div>

                    <div className="flex-1 md:w-32 p-4 rounded-xl border bg-purple-500/10 border-purple-500/30">
                        <div className="text-gray-400 text-xs uppercase font-bold flex items-center gap-2">
                            <TrendingUp size={14} /> Trades
                        </div>
                        <div className="text-2xl font-bold mt-1 text-purple-400">
                            {tradeCount}
                        </div>
                    </div>
                </div>
            </div>

            {/* Calendar Controls */}
            <div className="flex items-center justify-between bg-white/5 border border-white/10 p-4 rounded-xl backdrop-blur-sm">
                <button onClick={() => setCurrentMonth(subMonths(currentMonth, 1))} className="text-gray-300 hover:text-white hover:bg-white/10 p-2 rounded-lg transition">
                    &lt; Prev Month
                </button>
                <h2 className="text-xl font-bold text-white uppercase tracking-wider">
                    {format(currentMonth, 'MMMM yyyy')}
                </h2>
                <button onClick={() => setCurrentMonth(addMonths(currentMonth, 1))} className="text-gray-300 hover:text-white hover:bg-white/10 p-2 rounded-lg transition">
                    Next Month &gt;
                </button>
            </div>

            {/* Calendar Grid */}
            <div className="grid grid-cols-7 gap-4">
                {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(d => (
                    <div key={d} className="text-center text-xs uppercase font-bold text-gray-500 py-2">
                        {d}
                    </div>
                ))}

                {/* Empty Cells for alignment */}
                {emptyDays.map((_, i) => (
                    <div key={`empty-${i}`} className="aspect-square bg-transparent"></div>
                ))}

                {/* Day Cells */}
                {daysInMonth.map((day) => {
                    const { trades, pnl, count } = getDayData(day);
                    const isToday = isSameDay(day, new Date());

                    let bgClass = "bg-[#111] border-white/5"; // Default empty day
                    let textClass = "text-gray-500";

                    if (count > 0) {
                        if (pnl > 0) bgClass = "bg-green-500/20 border-green-500/40 hover:bg-green-500/30";
                        else if (pnl < 0) bgClass = "bg-red-500/20 border-red-500/40 hover:bg-red-500/30";
                        else bgClass = "bg-gray-700/50 border-gray-500/40"; // Break-even
                    }

                    if (isToday) bgClass += " ring-2 ring-blue-500";

                    return (
                        <div
                            key={day.toString()}
                            onClick={() => {
                                if (count > 0) {
                                    setSelectedDay(day);
                                }
                            }}
                            className={`relative aspect-square rounded-xl border p-3 flex flex-col justify-between transition-all group ${bgClass} ${count > 0 ? 'cursor-pointer' : 'cursor-default'}`}
                        >
                            <span className={`text-sm font-bold ${isSameDay(day, new Date()) ? 'text-blue-400' : 'text-gray-400'}`}>
                                {format(day, 'd')}
                            </span>

                            {count > 0 ? (
                                <div className="text-right">
                                    <div className={`text-lg md:text-xl font-bold ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        {pnl >= 0 ? '+' : ''}₹{Math.abs(pnl).toFixed(0)}
                                    </div>
                                    <div className="text-[10px] uppercase text-gray-400 mt-1">
                                        {count} Trade{count > 1 ? 's' : ''}
                                    </div>
                                </div>
                            ) : (
                                <div className="h-full flex items-center justify-center opacity-0 group-hover:opacity-20 transition-opacity">
                                    <div className="w-2 h-2 rounded-full bg-gray-500"></div>
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>

            {/* List of Trades for the Month (Below Calendar) */}
            <div className="mt-10">
                <h3 className="text-xl font-bold text-gray-300 mb-4 flex items-center gap-2">
                    <TrendingUp className="text-gray-500" size={20} /> Monthly Breakdown
                </h3>
                <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden backdrop-blur-sm">
                    <table className="w-full text-left text-sm">
                        <thead className="bg-[#111] uppercase text-xs text-gray-400">
                            <tr>
                                <th className="px-6 py-4">Date</th>
                                <th className="px-6 py-4">Symbol</th>
                                <th className="px-6 py-4 text-right">Qty</th>
                                <th className="px-6 py-4 text-right">Entry</th>
                                <th className="px-6 py-4 text-right">Exit</th>
                                <th className="px-6 py-4 text-right">P&L</th>
                                <th className="px-6 py-4 text-right">Reason</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/10">
                            {monthTrades.map((t, i) => (
                                <tr
                                    key={i}
                                    onClick={() => setSelectedTrade(t)}
                                    className="hover:bg-white/5 transition-colors cursor-pointer"
                                >
                                    <td className="px-6 py-4 text-gray-400 font-mono">
                                        {format(parseISO(t.entry_time), 'MMM d, HH:mm')}
                                    </td>
                                    <td className="px-6 py-4 font-bold text-white">{t.symbol}</td>
                                    <td className="px-6 py-4 text-right text-gray-400">{t.qty}</td>
                                    <td className="px-6 py-4 text-right font-mono text-gray-300">₹{t.entry_price}</td>
                                    <td className="px-6 py-4 text-right font-mono text-gray-300">₹{t.exit_price}</td>
                                    <td className={`px-6 py-4 text-right font-bold ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        {t.pnl >= 0 ? '+' : ''}₹{t.pnl?.toFixed(2)}
                                    </td>
                                    <td className="px-6 py-4 text-right text-xs uppercase text-gray-500">
                                        {t.exit_reason || t.status}
                                    </td>
                                </tr>
                            ))}
                            {monthTrades.length === 0 && (
                                <tr>
                                    <td colSpan={7} className="px-6 py-12 text-center text-gray-500">
                                        No trades found for this month.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
            {/* Trade Details Modal */}
            {selectedTrade && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200" onClick={() => setSelectedTrade(null)}>
                    <div
                        className="bg-[#0a0a0a] border border-white/10 rounded-2xl w-full max-w-lg overflow-hidden shadow-2xl relative animate-in zoom-in-95 duration-200"
                        onClick={e => e.stopPropagation()}
                    >

                        {/* Header */}
                        <div className="flex items-center justify-between p-6 border-b border-white/5 bg-white/5">
                            <div>
                                <h3 className="text-2xl font-bold text-white tracking-tight">{selectedTrade.symbol}</h3>
                                <div className="text-sm text-gray-400 font-mono mt-1 flex items-center gap-2">
                                    <Calendar size={12} />
                                    {format(parseISO(selectedTrade.entry_time), 'PPp')}
                                </div>
                            </div>
                            <button onClick={() => setSelectedTrade(null)} className="p-2 hover:bg-white/10 rounded-full transition-colors text-gray-400 hover:text-white">
                                <X size={20} />
                            </button>
                        </div>

                        {/* Content */}
                        <div className="p-6 space-y-6">

                            {/* P&L Hero */}
                            <div className={`text-center p-6 rounded-xl border ${selectedTrade.pnl >= 0 ? 'bg-green-500/10 border-green-500/20' : 'bg-red-500/10 border-red-500/20'}`}>
                                <div className="text-xs uppercase font-bold text-gray-400 mb-2 tracking-wider">Net P&L</div>
                                <div className={`text-5xl font-bold tracking-tighter ${selectedTrade.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    {selectedTrade.pnl >= 0 ? '+' : ''}₹{selectedTrade.pnl?.toFixed(2)}
                                </div>
                            </div>

                            {/* Grid Details */}
                            <div className="grid grid-cols-2 gap-4">
                                <div className="p-4 bg-white/5 rounded-xl border border-white/5 hover:border-white/10 transition-colors">
                                    <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Entry Price</div>
                                    <div className="font-mono text-xl text-white">₹{selectedTrade.entry_price}</div>
                                </div>
                                <div className="p-4 bg-white/5 rounded-xl border border-white/5 hover:border-white/10 transition-colors">
                                    <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Exit Price</div>
                                    <div className="font-mono text-xl text-white">₹{selectedTrade.exit_price}</div>
                                </div>
                                <div className="p-4 bg-white/5 rounded-xl border border-white/5 hover:border-white/10 transition-colors">
                                    <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Quantity</div>
                                    <div className="font-mono text-xl text-white">{selectedTrade.qty}</div>
                                </div>
                                <div className="p-4 bg-white/5 rounded-xl border border-white/5 hover:border-white/10 transition-colors">
                                    <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Invested</div>
                                    <div className="font-mono text-xl text-white">₹{(selectedTrade.entry_price * selectedTrade.qty).toFixed(0)}</div>
                                </div>
                            </div>

                            {/* Status / Reason */}
                            <div className="p-4 bg-white/5 rounded-xl border border-white/5">
                                <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Exit Reason</div>
                                <div className="text-sm text-gray-300 font-medium flex items-center gap-2">
                                    <span className="px-2 py-0.5 rounded-full bg-white/10 text-xs border border-white/10">
                                        {selectedTrade.status}
                                    </span>
                                    {selectedTrade.exit_reason}
                                </div>
                            </div>
                        </div>

                    </div>
                </div>
            )}

            {/* Day Trades Modal - Shows all trades for selected day */}
            {selectedDay && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200" onClick={() => setSelectedDay(null)}>
                    <div
                        className="bg-[#0a0a0a] border border-white/10 rounded-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden shadow-2xl relative animate-in zoom-in-95 duration-200"
                        onClick={e => e.stopPropagation()}
                    >
                        {/* Header */}
                        <div className="flex items-center justify-between p-6 border-b border-white/5 bg-white/5">
                            <div>
                                <h3 className="text-2xl font-bold text-white tracking-tight">
                                    {format(selectedDay, 'MMMM d, yyyy')}
                                </h3>
                                <div className="text-sm text-gray-400 mt-1">
                                    {getDayData(selectedDay).count} Trade{getDayData(selectedDay).count > 1 ? 's' : ''}
                                </div>
                            </div>
                            <button onClick={() => setSelectedDay(null)} className="p-2 hover:bg-white/10 rounded-full transition-colors text-gray-400 hover:text-white">
                                <X size={20} />
                            </button>
                        </div>

                        {/* Daily P&L Summary */}
                        <div className={`p-6 border-b border-white/5 ${getDayData(selectedDay).pnl >= 0 ? 'bg-green-500/10' : 'bg-red-500/10'}`}>
                            <div className="text-xs uppercase font-bold text-gray-400 mb-2 tracking-wider">Daily P&L</div>
                            <div className={`text-4xl font-bold tracking-tighter ${getDayData(selectedDay).pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                {getDayData(selectedDay).pnl >= 0 ? '+' : ''}₹{getDayData(selectedDay).pnl.toFixed(2)}
                            </div>
                        </div>

                        {/* Trade List */}
                        <div className="overflow-y-auto max-h-[400px] p-6 space-y-3">
                            {getDayData(selectedDay).trades.map((t: any, i: number) => (
                                <div
                                    key={i}
                                    onClick={() => {
                                        setSelectedDay(null);
                                        setSelectedTrade(t);
                                    }}
                                    className="bg-white/5 border border-white/10 rounded-xl p-4 hover:bg-white/10 transition-all cursor-pointer group"
                                >
                                    <div className="flex justify-between items-start mb-2">
                                        <div>
                                            <div className="font-bold text-white text-lg">{t.symbol}</div>
                                            <div className="text-xs text-gray-400 font-mono">
                                                {format(parseISO(t.entry_time), 'HH:mm')} → {t.exit_time ? format(parseISO(t.exit_time), 'HH:mm') : 'Open'}
                                            </div>
                                        </div>
                                        <div className="text-right">
                                            <div className={`text-xl font-bold ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                                {t.pnl >= 0 ? '+' : ''}₹{t.pnl?.toFixed(2)}
                                            </div>
                                            <div className="text-xs text-gray-500">Qty: {t.qty}</div>
                                        </div>
                                    </div>
                                    <div className="flex justify-between text-xs text-gray-400">
                                        <span>Entry: ₹{t.entry_price}</span>
                                        <span>Exit: ₹{t.exit_price}</span>
                                    </div>
                                    <div className="mt-2 text-xs text-gray-500 uppercase">
                                        {t.exit_reason || t.status}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
