"use client";
import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Home, Radio, TrendingUp, BookOpen, Settings, Terminal } from 'lucide-react';

const menuItems = [
    { name: 'Dashboard', icon: <Home size={20} />, path: '/' },
    { name: 'Live Signals', icon: <Radio size={20} />, path: '/signals' },
    { name: 'Active Trades', icon: <TrendingUp size={20} />, path: '/trades' },
    { name: 'Journal', icon: <BookOpen size={20} />, path: '/journal' },
    { name: 'Settings', icon: <Settings size={20} />, path: '/settings' },
    { name: 'Logs', icon: <Terminal size={20} />, path: '/logs' },
];

export default function Sidebar() {
    const pathname = usePathname();

    return (
        <aside className="hidden md:flex fixed left-0 top-0 h-screen w-64 bg-black/90 border-r border-white/10 backdrop-blur-xl flex-col z-50">
            <div className="p-6">
                <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-green-400 to-blue-500">
                    SENTINEL v2.0
                </h1>
                <p className="text-xs text-gray-500">Intraday Terminal</p>
            </div>

            <nav className="flex-1 px-4 space-y-2">
                {menuItems.map((item) => {
                    const isActive = pathname === item.path;
                    return (
                        <Link
                            key={item.path}
                            href={item.path}
                            className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200 ${isActive
                                ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30 shadow-[0_0_15px_rgba(0,100,255,0.2)]'
                                : 'text-gray-400 hover:bg-white/5 hover:text-white'
                                }`}
                        >
                            {item.icon}
                            <span className="font-medium">{item.name}</span>
                        </Link>
                    );
                })}
            </nav>

            <div className="p-4 border-t border-white/10">
                <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-green-400 to-blue-500 flex items-center justify-center font-bold text-black text-xs">
                        AB
                    </div>
                    <div>
                        <div className="text-sm font-semibold text-white">Ashbin</div>
                        <div className="text-xs text-gray-500">Pro Trader</div>
                    </div>
                </div>
            </div>
        </aside>
    );
}
