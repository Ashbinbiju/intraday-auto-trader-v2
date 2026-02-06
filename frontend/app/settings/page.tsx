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
        position_sizing: { mode: 'dynamic', risk_per_trade_pct: 1.0, max_position_size_pct: 20.0, min_sl_distance_pct: 0.6, paper_trading_balance: 100000 },
        limits: { max_trades_per_day: 3, max_trades_per_stock: 2, trading_end_time: "14:45", trading_start_time: "09:30" },
        general: { quantity: 1, check_interval: 300, dry_run: true },
        credentials: { dhan_client_id: "", dhan_access_token: "" }
    });

    useEffect(() => {
        axios.get(`${API_URL}/config`)
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
            // Use fallback to 0 to prevent NaN which causes 422
            const payload = {
                risk: {
                    stop_loss_pct: parseFloat(config.risk.stop_loss_pct as any) || 0.01,
                    target_pct: parseFloat(config.risk.target_pct as any) || 0.02,
                    trail_be_trigger: parseFloat(config.risk.trail_be_trigger as any) || 0.012
                },
                position_sizing: {
                    mode: config.position_sizing.mode || 'dynamic',
                    risk_per_trade_pct: parseFloat(config.position_sizing.risk_per_trade_pct as any) || 1.0,
                    max_position_size_pct: parseFloat(config.position_sizing.max_position_size_pct as any) || 20.0,
                    min_sl_distance_pct: parseFloat(config.position_sizing.min_sl_distance_pct as any) || 0.6,
                    paper_trading_balance: parseInt(config.position_sizing.paper_trading_balance as any) || 100000
                },
                limits: {
                    max_trades_per_day: parseInt(config.limits.max_trades_per_day as any) || 3,
                    max_trades_per_stock: parseInt(config.limits.max_trades_per_stock as any) || 2,
                    trading_start_time: config.limits.trading_start_time || "09:30",
                    trading_end_time: config.limits.trading_end_time || "14:45"
                },
                general: {
                    quantity: parseInt(config.general.quantity as any) || 1,
                    check_interval: 300,
                    dry_run: config.general.dry_run
                },
                credentials: {
                    dhan_client_id: config.credentials?.dhan_client_id || "",
                    dhan_access_token: config.credentials?.dhan_access_token || ""
                }
            };

            await axios.post(`${API_URL}/config`, payload);
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
                <div className="mx-2"></div>
                <button
                    onClick={async () => {
                        if (confirm("Are you sure you want to restart the backend server?")) {
                            try {
                                await axios.post(`${API_URL}/restart`);
                                alert("Server restart triggered. Please wait 30s.");
                            } catch (e) {
                                alert("Failed to trigger restart.");
                            }
                        }
                    }}
                    className="bg-red-600 hover:bg-red-500 px-4 py-2 rounded-lg font-bold text-sm"
                >
                    Restart Server
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

                {/* API Credentials */}
                <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                    <h3 className="text-xl font-bold mb-4 text-purple-400">API Credentials</h3>
                    <div className="space-y-4">
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Dhan Client ID (e.g., 100...)</label>
                            <input
                                type="text"
                                value={config.credentials?.dhan_client_id || ""}
                                onChange={(e) => handleChange('credentials', 'dhan_client_id', e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 focus:border-purple-500 outline-none"
                                placeholder="Enter Client ID"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Dhan Access Token (JWT)</label>
                            <textarea
                                value={config.credentials?.dhan_access_token || ""}
                                onChange={(e) => handleChange('credentials', 'dhan_access_token', e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 focus:border-purple-500 outline-none h-24 text-xs font-mono"
                                placeholder="eyJ..."
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
            </div>

            {/* Position Sizing - NEW FEATURE */}
            <div className="bg-gradient-to-br from-green-500/10 to-blue-500/10 border border-green-500/30 rounded-xl p-6">
                <h3 className="text-xl font-bold mb-4 text-green-400 flex items-center gap-2">
                    💰 Position Sizing
                    <span className="text-xs bg-green-500/20 text-green-300 px-2 py-1 rounded">NEW</span>
                </h3>

                {/* Mode Toggle */}
                <div className="mb-6 flex items-center justify-between p-4 bg-black/20 rounded-lg border border-dashed border-white/20">
                    <div>
                        <div className="font-bold text-gray-300">Dynamic Position Sizing</div>
                        <div className="text-xs text-gray-500">Auto-calculate quantity based on balance & SL</div>
                    </div>
                    <button
                        onClick={() => handleChange('position_sizing', 'mode', config.position_sizing.mode === 'dynamic' ? 'fixed' : 'dynamic')}
                        className={`px-4 py-2 rounded-lg text-xs font-bold transition-all border ${config.position_sizing.mode === 'dynamic' ? 'bg-green-500/20 text-green-400 border-green-500/50' : 'bg-gray-700/50 text-gray-400 border-gray-600'}`}
                    >
                        {config.position_sizing.mode === 'dynamic' ? 'ENABLED' : 'DISABLED'}
                    </button>
                </div>

                {config.position_sizing.mode === 'dynamic' && (
                    <div className="space-y-6">
                        {/* Risk Per Trade */}
                        <div>
                            <label className="block text-sm text-gray-400 mb-2">
                                Risk Per Trade: <span className="text-green-400 font-bold">{config.position_sizing.risk_per_trade_pct}%</span>
                            </label>
                            <input
                                type="range"
                                min="0.5"
                                max="2"
                                step="0.1"
                                value={config.position_sizing.risk_per_trade_pct}
                                onChange={(e) => handleChange('position_sizing', 'risk_per_trade_pct', parseFloat(e.target.value))}
                                className="w-full h-2 bg-black/40 rounded-lg appearance-none cursor-pointer accent-green-500"
                            />
                            <div className="flex justify-between text-xs text-gray-600 mt-1">
                                <span>0.5% (Conservative)</span>
                                <span>2% (Aggressive)</span>
                            </div>
                        </div>

                        {/* Max Position Size */}
                        <div>
                            <label className="block text-sm text-gray-400 mb-2">
                                Max Position Size: <span className="text-blue-400 font-bold">{config.position_sizing.max_position_size_pct}%</span>
                            </label>
                            <input
                                type="range"
                                min="10"
                                max="30"
                                step="5"
                                value={config.position_sizing.max_position_size_pct}
                                onChange={(e) => handleChange('position_sizing', 'max_position_size_pct', parseFloat(e.target.value))}
                                className="w-full h-2 bg-black/40 rounded-lg appearance-none cursor-pointer accent-blue-500"
                            />
                            <div className="flex justify-between text-xs text-gray-600 mt-1">
                                <span>10%</span>
                                <span>30%</span>
                            </div>
                        </div>

                        {/* Paper Trading Balance */}
                        <div>
                            <label className="block text-sm text-gray-400 mb-2">Paper Trading Balance (₹)</label>
                            <input
                                type="number"
                                step="10000"
                                value={config.position_sizing.paper_trading_balance}
                                onChange={(e) => handleChange('position_sizing', 'paper_trading_balance', parseInt(e.target.value) || 100000)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg p-3 focus:border-green-500 outline-none"
                                placeholder="100000"
                            />
                            <p className="text-xs text-gray-600 mt-1">Only used when Dry Run mode is enabled</p>
                        </div>

                        {/* Live Preview */}
                        <div className="bg-black/40 border border-green-500/30 rounded-lg p-4">
                            <h4 className="text-sm font-bold text-green-400 mb-2">📊 Live Preview</h4>
                            <div className="text-xs text-gray-400 space-y-1">
                                {(() => {
                                    const balance = config.position_sizing.paper_trading_balance;
                                    const riskPct = config.position_sizing.risk_per_trade_pct;
                                    const exampleEntry = 500;
                                    const exampleSL = 490;
                                    const slDist = exampleEntry - exampleSL;
                                    const riskAmount = (balance * riskPct) / 100;
                                    const qty = Math.floor(riskAmount / slDist);
                                    const exposure = qty * exampleEntry;
                                    const exposurePct = (exposure / balance) * 100;

                                    return (
                                        <>
                                            <p>Example: ₹{exampleEntry} entry, ₹{exampleSL} SL ({((slDist / exampleEntry) * 100).toFixed(1)}%)</p>
                                            <p>Risk Amount: <span className="text-green-400 font-mono">₹{riskAmount.toLocaleString()}</span></p>
                                            <p>Quantity: <span className="text-blue-400 font-mono font-bold">{qty} shares</span></p>
                                            <p>Exposure: <span className="text-orange-400 font-mono">₹{exposure.toLocaleString()} ({exposurePct.toFixed(1)}%)</span></p>
                                            <p className="text-green-300 mt-2">✅ Actual Risk: ₹{(qty * slDist).toLocaleString()} ({((qty * slDist / balance) * 100).toFixed(2)}%)</p>
                                        </>
                                    );
                                })()}
                            </div>
                        </div>
                    </div>
                )}

                {config.position_sizing.mode === 'fixed' && (
                    <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
                        <p className="text-sm text-yellow-400">
                            ⚠️ Fixed mode: Using quantity from General Settings ({config.general.quantity} shares per trade)
                        </p>
                    </div>
                )}
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
    );
}
