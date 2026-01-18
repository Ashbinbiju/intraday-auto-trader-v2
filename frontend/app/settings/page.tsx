"use client";
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Save } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function SettingsPage() {
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    const [config, setConfig] = useState({
        risk: { stop_loss_pct: 0.01, target_pct: 0.02, trail_be_trigger: 0.012 },
        limits: { max_trades_per_day: 3, max_trades_per_stock: 2, trading_end_time: "14:45", trading_start_time: "09:30" },
        general: { quantity: 1, check_interval: 300, dry_run: true }
    });

    useEffect(() => {
        axios.get(`${API_URL}/settings`)
            .then(res => {
                if (res.data) setConfig(res.data);
            })
            .catch(err => console.error("Error loading settings", err))
            .finally(() => setLoading(false));
    }, []);

    const handleChange = (section: string, key: string, value: any) => {
        setConfig(prev => ({
            ...prev,
            [section]: {
                ...prev[section as keyof typeof prev],
                [key]: value
            }
        }));
    };

    const saveSettings = async () => {
        setSaving(true);
        try {
            // Convert strings back to numbers for API
            const payload = {
                risk: {
                    stop_loss_pct: parseFloat(config.risk.stop_loss_pct as any),
                    target_pct: parseFloat(config.risk.target_pct as any),
                    trail_be_trigger: parseFloat(config.risk.trail_be_trigger as any)
                },
                limits: {
                    max_trades_per_day: parseInt(config.limits.max_trades_per_day as any),
                    max_trades_per_stock: parseInt(config.limits.max_trades_per_stock as any),
                    trading_end_time: config.limits.trading_end_time
                },
                general: {
                    quantity: parseInt(config.general.quantity as any),
                    check_interval: 300,
                    dry_run: config.general.dry_run
                }
            };

            await axios.post(`${API_URL}/settings`, payload);
            alert("Settings Saved Successfully!");
        } catch (err) {
            alert("Failed to save settings.");
            console.error(err);
        } finally {
            setSaving(false);
        }
    };

    if (loading) return <div className="p-10 text-center">Loading Settings...</div>;

    return (
        <div className="max-w-4xl mx-auto space-y-8">
            <div className="flex justify-between items-center">
                <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-gray-200 to-white">
                    Bot Configuration
                </h1>
                <button
                    onClick={saveSettings}
                    disabled={saving}
                    className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 px-6 py-2 rounded-lg font-bold transition-all disabled:opacity-50"
                >
                    <Save size={18} /> {saving ? 'Saving...' : 'Save Configuration'}
                </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Risk Rules */}
                <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                    <h3 className="text-xl font-bold mb-4 text-red-400">Risk Management</h3>
                    <div className="space-y-4">
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Stop Loss % (0.01 = 1%)</label>
                            <input
                                type="number" step="0.001"
                                value={config.risk.stop_loss_pct}
                                onChange={(e) => handleChange('risk', 'stop_loss_pct', e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 focus:border-blue-500 outline-none"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Target % (0.02 = 2%)</label>
                            <input
                                type="number" step="0.001"
                                value={config.risk.target_pct}
                                onChange={(e) => handleChange('risk', 'target_pct', e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 focus:border-blue-500 outline-none"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Trailing Activation %</label>
                            <input
                                type="number" step="0.001"
                                value={config.risk.trail_be_trigger}
                                onChange={(e) => handleChange('risk', 'trail_be_trigger', e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 focus:border-blue-500 outline-none"
                            />
                        </div>
                    </div>
                </div>

                {/* Trade Limits */}
                <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                    <h3 className="text-xl font-bold mb-4 text-orange-400">Trade Limits</h3>
                    <div className="space-y-4">
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Max Trades Per Day</label>
                            <input
                                type="number"
                                value={config.limits.max_trades_per_day}
                                onChange={(e) => handleChange('limits', 'max_trades_per_day', e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 focus:border-blue-500 outline-none"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Max Trades Per Stock</label>
                            <input
                                type="number"
                                value={config.limits.max_trades_per_stock}
                                onChange={(e) => handleChange('limits', 'max_trades_per_stock', e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 focus:border-blue-500 outline-none"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Trading Start Time (HH:MM)</label>
                            <input
                                type="time"
                                value={config.limits.trading_start_time || "09:30"}
                                onChange={(e) => handleChange('limits', 'trading_start_time', e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 focus:border-blue-500 outline-none"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Trading End Time (HH:MM)</label>
                            <input
                                type="time"
                                value={config.limits.trading_end_time}
                                onChange={(e) => handleChange('limits', 'trading_end_time', e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 focus:border-blue-500 outline-none"
                            />
                        </div>
                    </div>
                </div>

                {/* General */}
                <div className="bg-white/5 border border-white/10 rounded-xl p-6 md:col-span-2">
                    <h3 className="text-xl font-bold mb-4 text-blue-400 flex items-center gap-2">
                        General Settings
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Quantity Per Trade</label>
                            <input
                                type="number"
                                value={config.general.quantity}
                                onChange={(e) => handleChange('general', 'quantity', e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 focus:border-blue-500 outline-none transition-colors"
                            />
                        </div>
                        <div className="flex items-center justify-between p-4 bg-black/20 rounded-lg border border-dashed border-white/20">
                            <div>
                                <div className="font-bold text-gray-300">Dry Run Mode</div>
                                <div className="text-xs text-gray-500">Paper Trading (Simulated Orders)</div>
                            </div>
                            <button
                                onClick={() => handleChange('general', 'dry_run', !config.general.dry_run)}
                                className={`px-4 py-2 rounded-lg text-xs font-bold transition-all border ${config.general.dry_run ? 'bg-green-500/20 text-green-400 border-green-500/50' : 'bg-gray-700/50 text-gray-400 border-gray-600'}`}
                            >
                                {config.general.dry_run ? 'ACTIVE' : 'DISABLED'}
                            </button>
                        </div>
                    </div>
                    <p className="text-xs text-gray-600 mt-4 text-center">
                        * Changes to Risk and Limits apply immediately to the next trade. Restart not required.
                    </p>
                </div>
            </div>
        </div>
    );
}
