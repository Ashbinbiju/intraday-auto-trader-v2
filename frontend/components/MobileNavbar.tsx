"use client";
import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Home, Radio, TrendingUp, BookOpen, Settings, Terminal } from 'lucide-react';

const menuItems = [
    { name: 'Home', icon: <Home size={20} />, path: '/' },
    { name: 'Signals', icon: <Radio size={20} />, path: '/signals' },
    { name: 'Trades', icon: <TrendingUp size={20} />, path: '/trades' },
    { name: 'Journal', icon: <BookOpen size={20} />, path: '/journal' },
    { name: 'Logs', icon: <Terminal size={20} />, path: '/logs' },
    { name: 'Settings', icon: <Settings size={20} />, path: '/settings' },
];

export default function MobileNavbar() {
    const pathname = usePathname();

    return (
        <nav className="fixed bottom-0 left-0 w-full bg-black/90 backdrop-blur-xl border-t border-white/10 z-50 md:hidden pb-safe">
            <div className="flex justify-around items-center h-16">
                {menuItems.map((item) => {
                    const isActive = pathname === item.path;
                    return (
                        <Link
                            key={item.path}
                            href={item.path}
                            className={`flex flex-col items-center justify-center w-full h-full gap-1 transition-colors ${isActive
                                ? 'text-blue-400'
                                : 'text-gray-500 hover:text-white'
                                }`}
                        >
                            {item.icon}
                            <span className="text-[9px] font-medium leading-none">{item.name}</span>
                        </Link>
                    );
                })}
            </div>
        </nav>
    );
}
